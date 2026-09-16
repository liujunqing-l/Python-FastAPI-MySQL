import ExcelJS from 'exceljs'

/**
 * Create and download an .xlsx workbook in the browser.
 * `rows` must already contain display-ready values so data is not altered here.
 */
export async function exportWorkbook(filename, columns, rows) {
  const workbook = new ExcelJS.Workbook()
  workbook.creator = '运动员生命体征实时监控平台'
  workbook.created = new Date()

  const worksheet = workbook.addWorksheet('健康数据', {
    views: [{ state: 'frozen', ySplit: 1 }],
  })
  worksheet.columns = columns.map((column) => ({
    header: column.header,
    key: column.key,
    width: column.width || Math.max(String(column.header).length * 2 + 4, 14),
  }))
  rows.forEach((row) => worksheet.addRow(row))

  const heading = worksheet.getRow(1)
  heading.height = 23
  heading.font = { bold: true, color: { argb: 'FFFFFFFF' } }
  heading.alignment = { horizontal: 'center', vertical: 'middle' }
  heading.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF1D304D' } }
  worksheet.autoFilter = { from: 'A1', to: `${String.fromCharCode(64 + columns.length)}1` }

  worksheet.eachRow((row, index) => {
    if (index === 1) return
    row.alignment = { horizontal: 'center', vertical: 'middle' }
    row.eachCell((cell) => {
      cell.border = {
        bottom: { style: 'thin', color: { argb: 'FFCDD8E6' } },
      }
    })
  })

  const buffer = await workbook.xlsx.writeBuffer()
  const blob = new Blob([buffer], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename.endsWith('.xlsx') ? filename : `${filename}.xlsx`
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)

  return { filename: link.download, rowCount: rows.length }
}
