def fibonacci(n):
    if n <= 0:
        return []
    elif n == 1:
        return [0]
    secuencia = [0, 1]
    for _ in range(2, n):
        secuencia.append(secuencia[-1] + secuencia[-2])
    return secuencia