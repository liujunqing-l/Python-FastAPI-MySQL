const IMEI_PATTERN = /^\d{14,20}$/

export function parseLines(value) {
  return String(value ?? '')
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean)
}

export function parseImeis(value) {
  const imeis = parseLines(value)
  if (!imeis.length) throw new Error('请输入至少一个设备 IMEI')
  if (new Set(imeis).size !== imeis.length) throw new Error('设备 IMEI 不能重复')
  if (imeis.some((imei) => !IMEI_PATTERN.test(imei))) throw new Error('设备 IMEI 必须是 14–20 位数字')
  return imeis
}

export function bindingPairs(imeiText, nameText) {
  const imeis = parseImeis(imeiText)
  const names = parseLines(nameText)
  if (names.length && names.length !== imeis.length) {
    throw new Error('设备 IMEI 和人员姓名数量必须一致')
  }
  return imeis.map((imei, index) => ({ imei, name: names[index] || null }))
}

export function remainingBindings(currentImeis, removeText) {
  const remove = new Set(parseImeis(removeText))
  return [...new Set((currentImeis || []).map(String))].filter((imei) => !remove.has(imei))
}
