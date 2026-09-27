# NEÓN ESQUIVA

Juego arcade de reflejos hecho en Python con [raylib](https://www.raylib.com/). Esquiva los obstáculos de neón que caen desde arriba y sobrevive lo máximo posible para sumar puntos.

## Requisitos

- Python 3.10+
- `pip`

## Instalación y ejecución

```bash
pip install -r requirements.txt
python neon_dodge.py
```

## Controles

| Acción | Teclas |
| ------ | ------ |
| Moverse a la izquierda | `←` o `A` |
| Moverse a la derecha | `→` o `D` |
| Empezar / reintentar | `ESPACIO` o `ENTER` |
| Reiniciar partida | `R` |
| Cerrar el juego | `ESC` o cerrar la ventana |

También puedes mover al jugador deslizando el ratón.

## Cómo funciona

- El jugador se sitúa en la parte inferior de la pantalla y solo se mueve en el eje horizontal.
- Los obstáculos caen desde arriba; si te tocan, la partida termina.
- La dificultad aumenta con el tiempo: los obstáculos aparecen más rápido y caen a mayor velocidad.
- El **récord** (`RÉCORD`) se guarda durante la sesión. Al cerrar el juego se reinicia.

## Notas

- El juego genera sus efectos de sonido por código, por lo que no necesita archivos de audio externos.
- Modo simulación (sin ventana): `python neon_dodge.py --simulate [ticks]`.
- Autocomprobación: `python neon_dodge.py --self-test`.