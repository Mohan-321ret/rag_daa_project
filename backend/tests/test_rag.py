"""Run source-grounded questions through the existing DAA-RAG pipeline."""
from __future__ import annotations

import asyncio
import html
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


TEST_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TEST_DIR.parent
DATASET_PATH = TEST_DIR / "rag_test_data.json"
RESULTS_PATH = TEST_DIR / "results.json"
REPORT_PATH = TEST_DIR / "rag_test_report.html"

# App settings and the persisted FAISS index use paths relative to backend/.
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings
from app.core.permissions import Role
from app.db.database import SessionLocal, engine
from app.models.chunk import Chunk  # Register Document's SQLAlchemy relationship.
from app.models.document import Document
from app.models.user import User
from app.services.embedding_service import embed_batch
from app.services.rag_service import answer_question
from app.services.vector_store import get_vector_store


def _normalise_source(source: str) -> str:
    return Path(source).name.strip().casefold()


def _unique_sources(source_names: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for source in source_names:
        key = _normalise_source(source)
        if key not in seen:
            seen.add(key)
            unique.append(source)
    return unique


async def _run_queries(db, user: User, role: Role, cases: list[dict], names_by_id: dict[str, str]) -> list[dict]:
    results = []
    for case in cases:
        started = time.perf_counter()
        generated_answer = ""
        retrieved_sources: list[str] = []
        retrieved_chunks: list[dict] = []
        error = None
        model_used = None
        provider = None

        try:
            response = await answer_question(
                db=db,
                query=case["question"],
                current_user=user,
                caller_role=role,
                top_k=5,
            )
            generated_answer = response.get("answer") or ""
            model_used = response.get("model_used")
            provider = response.get("provider")
            for source in response.get("sources", []):
                document_id = source.get("document_id")
                document_name = names_by_id.get(
                    document_id,
                    f"Unknown source ({document_id})" if document_id else "Unknown source",
                )
                retrieved_sources.append(document_name)
                retrieved_chunks.append(
                    {
                        "document_id": document_id,
                        "document_name": document_name,
                        "chunk_index": source.get("chunk_index"),
                        "score": source.get("score"),
                        "text_preview": source.get("text_preview", ""),
                    }
                )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        elapsed = time.perf_counter() - started
        retrieved_sources = _unique_sources(retrieved_sources)
        retrieval_pass = _normalise_source(case["expected_source"]) in {
            _normalise_source(source) for source in retrieved_sources
        }
        results.append(
            {
                "id": case["id"],
                "question": case["question"],
                "ground_truth": case["ground_truth"],
                "generated_answer": generated_answer,
                "expected_source": case["expected_source"],
                "retrieved_sources": retrieved_sources,
                "retrieved_chunks": retrieved_chunks,
                "answer_similarity": None,
                "response_time": round(elapsed, 4),
                "retrieval_pass": retrieval_pass,
                "error": error,
                "model_used": model_used,
                "provider": provider,
            }
        )
        status = "PASS" if retrieval_pass else "FAIL"
        print(f"{status} {case['id']} ({elapsed:.2f}s) {case['question']}")
        if error:
            print(f"  Pipeline error: {error}")

    return results


def _calculate_answer_similarities(results: list[dict]) -> None:
    eligible = [result for result in results if result["generated_answer"].strip()]
    if not eligible:
        return

    texts = []
    for result in eligible:
        texts.extend((result["generated_answer"], result["ground_truth"]))

    vectors = embed_batch(texts)
    for index, result in enumerate(eligible):
        answer_vector = vectors[index * 2]
        truth_vector = vectors[index * 2 + 1]
        result["answer_similarity"] = round(
            sum(answer * truth for answer, truth in zip(answer_vector, truth_vector)), 4
        )


def _calculate_metrics(results: list[dict], evaluated_at: str) -> dict:
    total = len(results)
    passed = sum(result["retrieval_pass"] for result in results)
    response_times = [result["response_time"] for result in results]
    similarities = [
        result["answer_similarity"]
        for result in results
        if result["answer_similarity"] is not None
    ]

    def precision_at(k: int) -> float:
        if not total:
            return 0.0
        hits = sum(
            _normalise_source(result["expected_source"])
            in {_normalise_source(source) for source in result["retrieved_sources"][:k]}
            for result in results
        )
        return hits / (total * k)

    reciprocal_ranks = []
    for result in results:
        expected = _normalise_source(result["expected_source"])
        rank = next(
            (
                index
                for index, source in enumerate(result["retrieved_sources"], start=1)
                if _normalise_source(source) == expected
            ),
            None,
        )
        reciprocal_ranks.append(1 / rank if rank else 0.0)

    return {
        "evaluation_date": evaluated_at,
        "total_tests": total,
        "passed": passed,
        "failed": total - passed,
        "hit_rate": passed / total if total else 0.0,
        "precision_at_3": precision_at(3),
        "precision_at_5": precision_at(5),
        "mrr": sum(reciprocal_ranks) / total if total else 0.0,
        "average_answer_similarity": sum(similarities) / len(similarities) if similarities else None,
        "average_response_time": sum(response_times) / total if total else 0.0,
        "minimum_response_time": min(response_times) if response_times else 0.0,
        "maximum_response_time": max(response_times) if response_times else 0.0,
        "tests": results,
    }


def _percent(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:.1f}%"


def _number(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.3f}"


def _safe(value: object) -> str:
    return html.escape(str(value if value is not None else ""))


def _render_report(metrics: dict) -> str:
    cards = [
        ("Total Tests", str(metrics["total_tests"])),
        ("Passed", str(metrics["passed"])),
        ("Failed", str(metrics["failed"])),
        ("Hit Rate", _percent(metrics["hit_rate"])),
        ("Precision@5", _percent(metrics["precision_at_5"])),
        ("MRR", _number(metrics["mrr"])),
        ("Avg Answer Similarity", _number(metrics["average_answer_similarity"])),
        ("Avg Response Time", f"{metrics['average_response_time']:.2f}s"),
    ]
    cards_html = "\n".join(
        f'<div class="metric-card"><span>{_safe(label)}</span><strong>{_safe(value)}</strong></div>'
        for label, value in cards
    )

    rows = []
    for result in metrics["tests"]:
        status_class = "pass" if result["retrieval_pass"] else "fail"
        rows.append(
            "<tr>"
            f"<td>{_safe(result['id'])}</td>"
            f"<td>{_safe(result['question'])}</td>"
            f"<td>{_safe(result['expected_source'])}</td>"
            f"<td>{_safe(', '.join(result['retrieved_sources']) or 'None')}</td>"
            f"<td>{_safe(result['generated_answer'] or result['error'] or 'No answer')}</td>"
            f"<td>{_safe(result['ground_truth'])}</td>"
            f"<td>{_number(result['answer_similarity'])}</td>"
            f"<td>{result['response_time']:.2f}s</td>"
            f'<td class="{status_class}">{"PASS" if result["retrieval_pass"] else "FAIL"}</td>'
            "</tr>"
        )

    metric_values = [
        ("Retrieval Hit Rate", metrics["hit_rate"]),
        ("Precision@3", metrics["precision_at_3"]),
        ("Precision@5", metrics["precision_at_5"]),
        ("MRR", metrics["mrr"]),
        ("Average Answer Similarity", metrics["average_answer_similarity"]),
    ]
    metric_bars = []
    for label, value in metric_values:
        width = 0 if value is None else max(0, min(100, value * 100))
        metric_bars.append(
            f'<div class="bar-row"><span>{_safe(label)}</span>'
            f'<div class="bar-track"><div class="bar metric-bar" style="width:{width:.2f}%"></div></div>'
            f'<strong>{_number(value)}</strong></div>'
        )

    max_time = max((result["response_time"] for result in metrics["tests"]), default=0.0)
    time_bars = []
    for result in metrics["tests"]:
        width = result["response_time"] / max_time * 100 if max_time else 0
        time_bars.append(
            f'<div class="bar-row"><span>{_safe(result["id"])}</span>'
            f'<div class="bar-track"><div class="bar time-bar" style="width:{width:.2f}%"></div></div>'
            f'<strong>{result["response_time"]:.2f}s</strong></div>'
        )

    failed_results = [result for result in metrics["tests"] if not result["retrieval_pass"]]
    failed_html = []
    for result in failed_results:
        reason = result["error"] or "Expected source was not present in retrieved sources."
        failed_html.append(
            '<article class="failure">'
            f'<h3>{_safe(result["id"])}: {_safe(result["question"])}</h3>'
            f'<p><b>Expected source:</b> {_safe(result["expected_source"])}</p>'
            f'<p><b>Retrieved sources:</b> {_safe(", ".join(result["retrieved_sources"]) or "None")}</p>'
            f'<p><b>Generated answer:</b> {_safe(result["generated_answer"] or "No answer")}</p>'
            f'<p><b>Reason:</b> {_safe(reason)}</p>'
            "</article>"
        )
    if not failed_html:
        failed_html.append('<p class="empty">No retrieval failures.</p>')

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DAA-RAG Test Evaluation Report</title>
  <style>
    :root {{ color-scheme: light; --ink:#17232c; --muted:#60717a; --line:#dce4e8; --paper:#fff; --wash:#f3f7f8; --teal:#087f8c; --green:#13795b; --red:#b42332; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:var(--wash); color:var(--ink); font:14px/1.5 Segoe UI, sans-serif; }}
    main {{ max-width:1440px; margin:auto; padding:28px 22px 48px; }} header {{ border-bottom:1px solid var(--line); padding:0 0 20px; }}
    h1 {{ margin:0; font-size:26px; }} h2 {{ margin:30px 0 12px; font-size:18px; }} h3 {{ font-size:15px; margin:0 0 10px; }}
    .date,.note {{ color:var(--muted); }} .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; }}
    .metric-card {{ background:var(--paper); border:1px solid var(--line); border-radius:6px; padding:14px; }}
    .metric-card span {{ display:block; color:var(--muted); font-size:12px; }} .metric-card strong {{ display:block; margin-top:6px; font-size:22px; }}
    .table-wrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:6px; background:var(--paper); }}
    table {{ border-collapse:collapse; width:100%; min-width:1200px; }} th,td {{ text-align:left; vertical-align:top; padding:9px 10px; border-bottom:1px solid var(--line); }}
    th {{ background:#eaf1f3; font-size:12px; }} td {{ max-width:320px; overflow-wrap:anywhere; }} tr:last-child td {{ border-bottom:0; }}
    .pass {{ color:var(--green); font-weight:700; }} .fail {{ color:var(--red); font-weight:700; }}
    .charts {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr)); gap:16px; }}
    .chart {{ background:var(--paper); border:1px solid var(--line); border-radius:6px; padding:16px; }}
    .bar-row {{ display:grid; grid-template-columns:minmax(105px,1fr) minmax(100px,2fr) 54px; gap:10px; align-items:center; margin:9px 0; font-size:12px; }}
    .bar-row span {{ overflow-wrap:anywhere; }} .bar-row strong {{ text-align:right; font-variant-numeric:tabular-nums; }}
    .bar-track {{ height:9px; background:#e8eff1; border-radius:5px; overflow:hidden; }} .bar {{ height:100%; border-radius:5px; }}
    .metric-bar {{ background:var(--teal); }} .time-bar {{ background:#c27a18; }}
    .failure {{ background:var(--paper); border:1px solid #efc4c7; border-left:4px solid var(--red); border-radius:4px; padding:14px; margin:10px 0; }}
    .failure p {{ margin:6px 0; }} .empty {{ color:var(--green); }}
    @media(max-width:600px) {{ main {{ padding:20px 12px 32px; }} h1 {{ font-size:22px; }} .bar-row {{ grid-template-columns:85px minmax(60px,1fr) 48px; gap:6px; }} }}
  </style>
</head>
<body><main>
  <header><h1>DAA-RAG Test Evaluation Report</h1><div class="date">Evaluation date/time: {_safe(metrics['evaluation_date'])}</div></header>
  <h2>Summary</h2><section class="cards">{cards_html}</section>
  <h2>Test Results</h2><div class="table-wrap"><table><thead><tr><th>Test ID</th><th>Question</th><th>Expected Source</th><th>Retrieved Sources</th><th>Generated Answer</th><th>Ground Truth</th><th>Answer Similarity</th><th>Response Time</th><th>Status</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
  <h2>Metrics</h2><p class="note">Answer similarity is cosine similarity from the existing normalized sentence-embedding model. Precision@K uses distinct source documents and a fixed K denominator.</p>
  <section class="charts"><div class="chart"><h3>Retrieval and Answer Metrics</h3>{''.join(metric_bars)}</div><div class="chart"><h3>Response Time per Question</h3>{''.join(time_bars)}</div></section>
  <h2>Failed Tests</h2>{''.join(failed_html)}
</main></body></html>"""


def main() -> int:
    with DATASET_PATH.open(encoding="utf-8") as dataset_file:
        cases = json.load(dataset_file)
    if not cases:
        raise RuntimeError("The RAG test dataset is empty.")

    engine.echo = False
    db = SessionLocal()
    original_query_logging = settings.query_logging_enabled
    settings.query_logging_enabled = False
    try:
        user = (
            db.query(User)
            .filter(User.is_active.is_(True), User.role == Role.PLATFORM_OWNER.value)
            .order_by(User.created_at)
            .first()
        )
        if user is None:
            raise RuntimeError("An existing active platform_owner account is required to run the evaluation.")

        role = Role(user.role)
        documents = db.query(Document).all()
        names_by_id = {document.document_id: document.original_filename for document in documents}
        available_names = {
            _normalise_source(document.original_filename)
            for document in documents
            if document.processing_status == "indexed"
        }
        missing_sources = sorted(
            {case["expected_source"] for case in cases if _normalise_source(case["expected_source"]) not in available_names}
        )
        if missing_sources:
            raise RuntimeError("Expected source document(s) are not indexed: " + ", ".join(missing_sources))

        store = get_vector_store()
        if store.total == 0:
            raise RuntimeError("The existing FAISS index is empty; ingest/index the source documents first.")

        print(f"Running {len(cases)} real RAG queries with provider={settings.llm_provider}, indexed_vectors={store.total}.")
        with patch("app.services.ticket_service.is_ticketing_enabled", return_value=False):
            results = asyncio.run(_run_queries(db, user, role, cases, names_by_id))

        _calculate_answer_similarities(results)
        evaluated_at = datetime.now().astimezone().isoformat(timespec="seconds")
        metrics = _calculate_metrics(results, evaluated_at)
        RESULTS_PATH.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        REPORT_PATH.write_text(_render_report(metrics), encoding="utf-8")

        print(f"\nPassed: {metrics['passed']}/{metrics['total_tests']} | Hit rate: {_percent(metrics['hit_rate'])}")
        print(f"Precision@3: {_percent(metrics['precision_at_3'])} | Precision@5: {_percent(metrics['precision_at_5'])} | MRR: {_number(metrics['mrr'])}")
        print(f"Average answer similarity: {_number(metrics['average_answer_similarity'])}")
        print(
            "Response time (avg/min/max): "
            f"{metrics['average_response_time']:.2f}s / "
            f"{metrics['minimum_response_time']:.2f}s / "
            f"{metrics['maximum_response_time']:.2f}s"
        )
        print(f"Results: {RESULTS_PATH}")
        print(f"HTML report: {REPORT_PATH}")
        return 0
    finally:
        settings.query_logging_enabled = original_query_logging
        db.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"RAG evaluation could not complete: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)