// 用系统 Chrome 给 React 客服控制台截图（真实对话流）
import { chromium } from 'playwright-core'
import fs from 'node:fs'

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const OUT = 'D:/RAG/assets'
fs.mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({ executablePath: CHROME, headless: true })
const page = await browser.newPage({ viewport: { width: 1560, height: 900 }, deviceScaleFactor: 1.6 })

await page.goto('http://[::1]:5174/', { waitUntil: 'networkidle', timeout: 60000 })

async function send(q) {
  const inp = page.locator('input[placeholder*="输入问题"]')
  await inp.fill(q)
  await inp.press('Enter')
  await page.waitForTimeout(1800) // 等待 bot 回复
}
async function ask(q) {
  await send(q)
  // 等最后一个 .msg.bot 出现再等 600ms
  await page.waitForSelector('.msg.bot', { timeout: 30000 })
  await page.waitForTimeout(700)
}

// 场景 1：商品咨询 + 追问（演示元数据过滤与会话记忆）
await page.goto('http://[::1]:5174/', { waitUntil: 'networkidle', timeout: 60000 })
await page.waitForSelector('.inputbar', { timeout: 30000 })
await ask('这个耳机能续航多久？')
await ask('那防水吗？')
await page.waitForTimeout(500)

// 顶部加一个商品过滤提示可见即可，截图直接取全部
await page.screenshot({ path: OUT + '/web_demo_main.png' })

// 场景 2：清空会话再问一个投诉类问题（触发转人工），展示 need_human 徽标
await ask('东西太差不想要了，我要投诉你们！')
await page.waitForTimeout(700)
await page.screenshot({ path: OUT + '/web_demo_human.png' })

// 场景 3：统计面板（滚动右栏到统计可见，其实常驻）。直接裁右侧统计区
const statsBox = page.locator('.stats')
await statsBox.scrollIntoViewIfNeeded()
await page.waitForTimeout(400)
await statsBox.screenshot({ path: OUT + '/web_stats.png' })

await browser.close()
console.log('screenshots done:', fs.readdirSync(OUT).filter(f => f.startsWith('web_')))