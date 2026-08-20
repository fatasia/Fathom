const { chromium } = require('playwright')
const path = require('node:path')
const fs = require('node:fs')

async function main() {
  const outputDirectory = path.resolve('artifacts', 'visual-smoke')
  fs.mkdirSync(outputDirectory, { recursive: true })
  const browser = await chromium.launch({ channel: 'chrome', headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const runtimeErrors = []
  page.on('pageerror', (error) => runtimeErrors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') runtimeErrors.push(message.text())
  })

  await page.goto('http://127.0.0.1:8000', { waitUntil: 'networkidle' })
  await page.screenshot({ path: path.join(outputDirectory, '01-ask.png'), fullPage: true })

  const screens = [
    ['业务知识', '02-ontology.png'],
    ['指标中心', '03-metrics.png'],
    ['智能体网络', '04-agents.png'],
    ['数据连接', '05-connections.png'],
    ['工程工具', '06-studio.png'],
    ['学习与治理', '07-governance.png'],
    ['系统设置', '08-settings.png'],
  ]
  for (const [label, filename] of screens) {
    await page.getByRole('button', { name: label, exact: true }).click()
    await page.waitForTimeout(250)
    await page.screenshot({ path: path.join(outputDirectory, filename), fullPage: true })
  }

  await page.getByRole('button', { name: '业务知识', exact: true }).click()
  await page.getByRole('button', { name: '新建业务域', exact: true }).click()
  await page.screenshot({ path: path.join(outputDirectory, '09-builder.png'), fullPage: true })

  const layout = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    documentWidth: document.documentElement.scrollWidth,
    documentHeight: document.documentElement.scrollHeight,
  }))
  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } })
  mobile.on('pageerror', (error) => runtimeErrors.push(`mobile: ${error.message}`))
  mobile.on('console', (message) => {
    if (message.type() === 'error') runtimeErrors.push(`mobile: ${message.text()}`)
  })
  await mobile.goto('http://127.0.0.1:8000', { waitUntil: 'networkidle' })
  await mobile.screenshot({ path: path.join(outputDirectory, '10-mobile-ask.png'), fullPage: true })
  await mobile.getByRole('button', { name: '打开导航' }).click()
  await mobile.getByRole('button', { name: '工程工具', exact: true }).click()
  await mobile.waitForTimeout(400)
  await mobile.screenshot({ path: path.join(outputDirectory, '11-mobile-studio.png'), fullPage: true })
  await mobile.getByRole('button', { name: '打开导航' }).click()
  await mobile.getByRole('button', { name: '学习与治理', exact: true }).click()
  await mobile.waitForTimeout(400)
  await mobile.screenshot({ path: path.join(outputDirectory, '12-mobile-governance.png'), fullPage: true })
  const mobileLayout = await mobile.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    documentWidth: document.documentElement.scrollWidth,
    documentHeight: document.documentElement.scrollHeight,
  }))
  await browser.close()
  if (runtimeErrors.length) throw new Error(`Browser errors: ${runtimeErrors.join(' | ')}`)
  if (layout.documentWidth > layout.viewport + 1) {
    throw new Error(`Horizontal overflow: ${JSON.stringify(layout)}`)
  }
  if (mobileLayout.documentWidth > mobileLayout.viewport + 1) {
    throw new Error(`Mobile horizontal overflow: ${JSON.stringify(mobileLayout)}`)
  }
  process.stdout.write(JSON.stringify({ ok: true, layout, mobileLayout, screenshots: 12 }, null, 2))
}

main().catch((error) => {
  process.stderr.write(`${error.stack}\n`)
  process.exit(1)
})
