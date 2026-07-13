// Wrapper generico de fetch para la API REST del backend. Sin dependencias.

export async function apiFetch(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok || !data.ok) {
    throw new Error(data.error || "Error de API");
  }
  return data;
}
