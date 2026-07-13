// Estado compartido entre modulos (vista de detalle de cuenta actualmente
// abierta). Se exporta como objeto mutable: cualquier modulo puede leer o
// escribir sus propiedades y los demas ven el cambio de inmediato, sin
// necesitar funciones getter/setter para cada campo.

export const appState = {
  currentDetailAccountId: null,
  currentDetailTransactions: [],
};
