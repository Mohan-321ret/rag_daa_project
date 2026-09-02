const { spawn } = require('child_process')
const path = require('path')

const nodeDir = path.dirname(process.execPath)
const npmCli = path.join(__dirname, 'npm-cli', 'bin', 'npm-cli.js')

const env = { ...process.env, PATH: nodeDir + ';' + process.env.PATH }

const child = spawn(process.execPath, [npmCli, 'run', 'dev'], {
  cwd: __dirname,
  env,
  stdio: 'inherit',
  shell: false,
})

child.on('exit', code => process.exit(code))
