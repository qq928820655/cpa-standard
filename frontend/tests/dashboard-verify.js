import { chromium } from '@playwright/test'

const MASTER_KEY = 'cpa-ufN5DGQb7UlfB0ZKCPtHwrKMKSnmEz90vTKAy_JFjLU'
const VIEW_STATE_KEYS = [
  'keyManageViewState',
  'keyManageFiltersCollapsed',
  'dashboardViewState',
  'usageStatsViewState',
]

async function main() {
  const browser = await chromium.launch({ channel: 'chrome', headless: false })
  const page = await browser.newPage({ baseURL: 'http://127.0.0.1:8000' })

  try {
    await page.addInitScript(({ masterKey, stateKeys }) => {
      localStorage.setItem('masterKey', masterKey)
      stateKeys.forEach((key) => localStorage.removeItem(key))
    }, { masterKey: MASTER_KEY, stateKeys: VIEW_STATE_KEYS })

    await page.goto('/dashboard', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await page.getByRole('heading', { name: '仪表盘' }).waitFor({ timeout: 30000 })
    await page.locator('.dashboard-key-table .el-table__body-wrapper tbody tr').first().waitFor({ timeout: 30000 })

    const keyCard = page.locator('.key-list-card')
    const tableBody = page.locator('.dashboard-key-table .el-table__body-wrapper')
    const tableHeader = page.locator('.dashboard-key-table .el-table__header-wrapper')
    const stickyHeader = page.locator('.dashboard-key-sticky')

    const before = {
      keyCardTop: await keyCard.boundingBox().then((box) => box?.y ?? null),
      headerTop: await tableHeader.boundingBox().then((box) => box?.y ?? null),
      bodyTop: await tableBody.boundingBox().then((box) => box?.y ?? null),
      stickyTop: await stickyHeader.boundingBox().then((box) => box?.y ?? null),
    }

    await tableBody.evaluate((el) => { el.scrollTop = 600 })
    await page.waitForTimeout(800)

    const after = {
      headerTop: await tableHeader.boundingBox().then((box) => box?.y ?? null),
      bodyTop: await tableBody.boundingBox().then((box) => box?.y ?? null),
      stickyTop: await stickyHeader.boundingBox().then((box) => box?.y ?? null),
      firstRowTop: await page.locator('.dashboard-key-table .el-table__body-wrapper tbody tr').first().boundingBox().then((box) => box?.y ?? null),
      headerText: await tableHeader.innerText(),
    }

    const result = { before, after }
    console.log(JSON.stringify(result, null, 2))
  } finally {
    await browser.close()
  }
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
