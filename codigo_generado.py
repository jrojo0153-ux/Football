def fibonacci(n: int) -> list[int]:
    if not isinstance(n, int):
        raise TypeError("El parámetro 'n' debe ser un número entero.")
    if n <= 0:
        return []
    if n == 1:
        return [0]
    
    secuencia = [0] * n
    secuencia[1] = 1
    for i in range(2, n):
        secuencia[i] = secuencia[i - 1] + secuencia[i - 2]
    return secuencia