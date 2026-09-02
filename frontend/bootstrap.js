// Bootstrap: download npm via corepack or install-npm-globally
const https = require('https')
const fs = require('fs')
const path = require('path')
const { execSync } = require('child_process')

const NODE = process.execPath

// Check if npm exists next to node
const npmCli = path.join(path.dirname(NODE), 'npm')
const npmCmd = path.join(path.dirname(NODE), 'npm.cmd')

console.log('Node path:', NODE)
console.log('Node version:', process.version)

// Try to find npm in PATH
try {
  const v = execSync('npm --version', { encoding: 'utf8', env: { ...process.env, PATH: path.dirname(NODE) + ';' + process.env.PATH } })
  console.log('npm version:', v.trim())
} catch(e) {
  console.log('npm not found, will use npx via node to install')
}

// Download npm tarball and extract
const NPM_URL = 'https://registry.npmjs.org/npm/-/npm-10.8.2.tgz'
const dest = path.join(__dirname, 'npm-pkg.tgz')

console.log('Downloading npm...')
const file = fs.createWriteStream(dest)
https.get(NPM_URL, res => {
  res.pipe(file)
  file.on('finish', () => {
    file.close()
    console.log('Downloaded npm tarball')
    try {
      execSync(`"${NODE}" -e "require('zlib')"`)
      // Extract using node built-ins
      execSync(`tar -xzf npm-pkg.tgz -C . --strip-components=1 --one-top-level=npm-cli`, { cwd: __dirname, stdio: 'inherit' })
      console.log('Extracted npm')
    } catch(e) {
      console.error('Extraction error:', e.message)
    }
  })
}).on('error', err => {
  console.error('Download error:', err.message)
})
