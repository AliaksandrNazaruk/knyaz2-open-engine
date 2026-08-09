// Округление сопроцессора (`fistp`), которым движок заканчивает расчёты цены,
// урона, крепости зелий и сроков работ: к ближайшему, а ровно на половине — к
// ЧЁТНОМУ. Math.round в этом месте округляет половину вверх и расходится на 1:
// 2.5 у движка даёт 2, а не 3.
//
// Лежит отдельным модулем, потому что нужно и торговле, и бою, и зельям, и
// деревне: пока функция жила в trade.js, цепочка carry → effects → trade →
// carry замыкалась в петлю импортов.
export function roundHalfEven(value) {
  const floor = Math.floor(value);
  const rest = value - floor;
  if (rest > 0.5) return floor + 1;
  if (rest < 0.5) return floor;
  return floor % 2 === 0 ? floor : floor + 1;
}
