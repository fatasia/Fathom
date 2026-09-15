const { chromium } = require('playwright')
const path = require('node:path')
const fs = require('node:fs')

async function main() {
  const baseUrl = process.env.FATHOM_BASE_URL || 'http://127.0.0.1:8000'
  const outputDirectory = path.resolve('docs', 'assets', 'screenshots')
  fs.mkdirSync(outputDirectory, { recursive: true })
  const browser = await chromium.launch({ channel: 'chrome', headless: true })
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    permissions: ['clipboard-read', 'clipboard-write'],
  })
  const page = await context.newPage()
  const runtimeErrors = []
  page.on('pageerror', (error) => runtimeErrors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') runtimeErrors.push(message.text())
  })

  await page.goto(baseUrl, { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: '新对话', exact: true }).click()
  await page.screenshot({ path: path.join(outputDirectory, '01-ask.png'), fullPage: true })
  await page.getByRole('button', { name: '昨天的 OEE 是多少？', exact: true }).click()
  await page.locator('.result-card').waitFor()
  await page.getByRole('button', { name: '思考与执行', exact: true }).click()
  await page.screenshot({ path: path.join(outputDirectory, '01b-ask-result.png'), fullPage: true })

  const conversationCount = await page.locator('.history-item').count()
  if (conversationCount < 1) throw new Error('Conversation history was not persisted')

  const primaryScreens = [
    ['业务知识', '02-ontology.png'],
    ['知识库', '02b-knowledge.png'],
    ['数据接入', '05-connections.png'],
  ]
  for (const [label, filename] of primaryScreens) {
    await page.getByRole('button', { name: label, exact: true }).click()
    await page.waitForTimeout(250)
    if (label === '数据接入') {
      const integrationCount = await page.locator('.connection-grid button').count()
      if (integrationCount !== 3) throw new Error(`Expected 3 one-click integrations, got ${integrationCount}`)
      await page.getByRole('button', { name: /工作流 \/ 低代码平台/ }).click()
      const openApiClipboard = await page.evaluate(() => navigator.clipboard.readText())
      if (!openApiClipboard.includes('/api/v1/integrations/dify/openapi.yaml')) {
        throw new Error(`OpenAPI clipboard is invalid: ${openApiClipboard}`)
      }
      await page.getByRole('button', { name: /Agent 软件/ }).click()
      const agentClipboard = await page.evaluate(() => navigator.clipboard.readText())
      if (!agentClipboard.includes('mcpServers') || !agentClipboard.includes('a2aAgentCard')) {
        throw new Error(`Agent clipboard is invalid: ${agentClipboard}`)
      }
      const visibleConnectorCount = await page.locator('.connector-matrix article').count()
      if (visibleConnectorCount !== 6) throw new Error(`Expected 6 default connectors, got ${visibleConnectorCount}`)
      await page.getByRole('button', { name: /查看全部 \d+ 种/ }).click()
      const expandedConnectorCount = await page.locator('.connector-matrix article').count()
      if (expandedConnectorCount <= visibleConnectorCount) {
        throw new Error(`Connector expansion failed: ${expandedConnectorCount}`)
      }
      await page.getByRole('button', { name: '收起类型', exact: true }).click()
    }
    await page.screenshot({ path: path.join(outputDirectory, filename), fullPage: true })
  }

  await page.getByRole('button', { name: '高级管理', exact: true }).click()
  const advancedScreens = [
    ['指标中心', '03-metrics.png'],
    ['智能体网络', '04-agents.png'],
    ['工程工具', '06-studio.png'],
    ['学习与治理', '07-governance.png'],
  ]
  for (const [label, filename] of advancedScreens) {
    await page.getByRole('button', { name: label, exact: true }).click()
    await page.waitForTimeout(250)
    await page.screenshot({ path: path.join(outputDirectory, filename), fullPage: true })
  }
  await page.getByRole('button', { name: '系统设置', exact: true }).click()
  await page.waitForTimeout(400)
  await page.screenshot({ path: path.join(outputDirectory, '08-settings.png'), fullPage: true })

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
  await mobile.goto(baseUrl, { waitUntil: 'networkidle' })
  await mobile.screenshot({ path: path.join(outputDirectory, '10-mobile-ask.png'), fullPage: true })
  await mobile.getByRole('button', { name: '打开导航' }).click()
  await mobile.getByRole('button', { name: '高级管理', exact: true }).click()
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
  process.stdout.write(JSON.stringify({ ok: true, layout, mobileLayout, screenshots: 14 }, null, 2))
}

main().catch((error) => {
  process.stderr.write(`${error.stack}\n`)
  process.exit(1)
})
