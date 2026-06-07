import logging

logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"}'
)
logger = logging.getLogger("fibonacci_service")

def fibonacci(n: int) -> list[int]:
    logger.info("Iniciando cálculo de Fibonacci para n=%s", n)
    try:
        if not isinstance(n, int):
            raise TypeError("El parámetro 'n' debe ser un número entero.")
    except TypeError as e:
        logger.error("Error de validación en los parámetros de entrada: %s", str(e), exc_info=True)
        raise

    if n <= 0:
        logger.warning("Se recibió un valor n=%s menor o igual a 0. Retornando lista vacía.", n)
        return []
    if n == 1:
        logger.info("Caso base alcanzado para n=1. Retornando [0]")
        return [0]
    
    secuencia = [0] * n
    secuencia[1] = 1
    for i in range(2, n):
        secuencia[i] = secuencia[i - 1] + secuencia[i - 2]
    
    logger.info("Cálculo de Fibonacci completado con éxito para n=%s", n)
    return secuencia