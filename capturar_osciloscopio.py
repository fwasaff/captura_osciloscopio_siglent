"""
Captura un transitorio de un osciloscopio Siglent serie SDS1000(CNL+) por USB
(SCPI/USBTMC) y lo guarda como CSV de dos columnas: tiempo [s], voltaje [V].

Herramienta genérica: no asume nada sobre el experimento. Sirve para cualquier
señal que el osciloscopio pueda capturar (circuitos RC/RLC, sensores ópticos,
acelerómetros, lo que sea), no solo para el proyecto de gemelo digital RLC en
el que se usó por primera vez. Ver README.md para una guía completa.

Requiere: numpy, pyvisa (ver requirements.txt) y, según el sistema operativo,
o bien VISA instalado (Windows/macOS: NI-VISA o Keysight IO Libraries) o bien
pyvisa-py + pyusb + la regla udev de este repositorio (Linux). Ver README.md,
sección Instalación, para los pasos específicos de cada sistema.

Uso:
    python capturar_osciloscopio.py [-h] [canal] [archivo_salida] [--sin-disparo] [--streaming]
    python capturar_osciloscopio.py C1 traza_real.csv
    python capturar_osciloscopio.py --streaming
    python capturar_osciloscopio.py --help

Por defecto arma un disparo SINGLE y espera a que el osciloscopio capture.
Si el osciloscopio ya está detenido con la traza que quieres (p. ej. la
armaste manualmente desde el panel), usa --sin-disparo para leerla tal cual.

--streaming abre un gráfico que se va actualizando con cada captura nueva
(Ctrl+C para detener). No es streaming continuo del ADC -- cada actualización
es una captura SINGLE completa, repetida tan rápido como el osciloscopio y el
USB lo permitan (en la práctica, unos pocos Hz). Si tu fenómeno se repite más
rápido que eso, vas a perderte disparos entre una descarga y la siguiente.

Referencia: Siglent Digital Oscilloscopes Programming Guide, secciones
WAVEFORM (WF?) y WAVEFORM_SETUP (WFSU).
"""

import argparse
import re
import time

import numpy as np
import pyvisa

GRID_HORIZONTAL = 14  # divisiones horizontales de pantalla en la serie SDS1000

_PREFIJOS_SI = {'p': 1e-12, 'n': 1e-9, 'u': 1e-6, 'µ': 1e-6, 'm': 1e-3,
                'k': 1e3, 'K': 1e3, 'M': 1e6, 'G': 1e9}
_RE_NUMERO = re.compile(r'^([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s*(.*)$')


def _abrir_resource_manager():
    """Usa VISA del sistema si está instalado (NI-VISA, Keysight IO Libraries);
    si no, recurre al backend puro de Python (pyvisa-py).

    Esto es lo que hace que el mismo script funcione en Windows/macOS (donde
    lo más simple es instalar NI-VISA y no tocar nada más) y en Linux (donde
    pyvisa-py + la regla udev de este repositorio evita instalar nada extra).
    pyvisa.ResourceManager() sin argumentos falla si no encuentra una VISA de
    sistema -- por eso el try/except, no es un error real del programa.
    """
    try:
        return pyvisa.ResourceManager()
    except Exception:
        return pyvisa.ResourceManager('@py')


def conectar():
    """Abre el primer instrumento USBTMC que se encuentre.

    El error de permisos es, en la práctica, el motivo más común por el que
    esto falla la primera vez que un/a estudiante lo prueba en un computador
    nuevo -- de ahí el mensaje explícito en vez de dejar pasar la traza cruda
    de Python.
    """
    rm = _abrir_resource_manager()
    recursos = rm.list_resources()
    if not recursos:
        raise RuntimeError(
            "No se encontró ningún instrumento USBTMC conectado. Verifica el "
            "cable USB y que el osciloscopio esté encendido. En Windows/macOS, "
            "verifica además que tengas instalado NI-VISA o Keysight IO "
            "Libraries Suite (ver README.md, sección Instalación)."
        )
    try:
        osc = rm.open_resource(recursos[0])
    except PermissionError as exc:
        raise PermissionError(
            "Sin permiso para acceder al instrumento USB. En Linux: revisa "
            "que la regla udev 99-usbtmc-siglent.rules esté instalada (ver "
            "README.md, sección Instalación) y reconecta el cable USB tras "
            "instalarla."
        ) from exc
    osc.timeout = 15000
    osc.chunk_size = 1024 * 1024
    return osc


def armar_y_esperar_disparo(osc, timeout_s=30.0):
    """Arma un disparo único y espera a que el osciloscopio capture (TRMD -> STOP)."""
    osc.write('TRMD SINGLE')
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        time.sleep(0.2)
        estado = osc.query('TRMD?').strip()
        if 'STOP' in estado.upper():
            return
    raise TimeoutError(
        "No se detectó disparo en el tiempo de espera. "
        "Verifica el nivel/fuente de trigger en el osciloscopio."
    )


def leer_parametro_numerico(osc, comando):
    """Envía un comando ?-query tipo 'C1:VDIV?' y devuelve el valor en unidades SI base.

    Las respuestas vienen como '<token> <numero><prefijo><unidad>', p.ej.
    'TRDL 68.20000us' o 'SARA 100.0MSa'. Se interpreta el prefijo de
    ingeniería (u, m, k, M, ...) para devolver siempre la unidad base
    (segundos, voltios, muestras/s).
    """
    resp = osc.query(comando).strip()
    token = resp.split()[-1]
    m = _RE_NUMERO.match(token)
    if not m:
        raise ValueError(f"No se pudo interpretar la respuesta '{resp}' al comando '{comando}'")
    numero, sufijo = m.groups()
    factor = _PREFIJOS_SI.get(sufijo[0], 1.0) if sufijo else 1.0
    return float(numero) * factor


def descargar_forma_onda(osc, canal):
    """Descarga la forma de onda binaria DAT2 de <canal> y la devuelve como bytes crudos."""
    osc.write(f'{canal}:WFSU SP,0,NP,0,FP,0')
    osc.write(f'{canal}:WF? DAT2')
    crudo = osc.read_raw()

    marca = crudo.find(b'#9')
    if marca == -1:
        raise ValueError("No se encontró el marcador de bloque binario '#9' en la respuesta.")

    inicio_len = marca + 2
    longitud = int(crudo[inicio_len:inicio_len + 9])
    inicio_datos = inicio_len + 9
    datos = crudo[inicio_datos:inicio_datos + longitud]

    if len(datos) != longitud:
        raise ValueError(f"Longitud de datos inconsistente: esperados {longitud}, recibidos {len(datos)}")
    return datos


def capturar_canal(osc, canal='C1', esperar_disparo=True):
    if esperar_disparo:
        armar_y_esperar_disparo(osc)

    vdiv = leer_parametro_numerico(osc, f'{canal}:VDIV?')
    voffset = leer_parametro_numerico(osc, f'{canal}:OFST?')
    tdiv = leer_parametro_numerico(osc, 'TDIV?')
    trdl = leer_parametro_numerico(osc, 'TRDL?')
    sara = leer_parametro_numerico(osc, 'SARA?')

    crudo = descargar_forma_onda(osc, canal)
    codigos = np.frombuffer(crudo, dtype=np.int8).astype(np.float64)

    voltaje = codigos * (vdiv / 25.0) - voffset

    dt = 1.0 / sara
    t0 = trdl - (tdiv * GRID_HORIZONTAL / 2.0)
    tiempo = t0 + dt * np.arange(len(voltaje))

    return tiempo, voltaje


def guardar_csv(tiempo, voltaje, archivo_salida):
    datos = np.column_stack([tiempo, voltaje])
    np.savetxt(archivo_salida, datos, delimiter=',', header='tiempo[s],voltaje[V]',
               comments='', fmt='%.9e')


def stream_capturas(osc, canal='C1', esperar_disparo=True):
    """Generador infinito: repite 'capturar_canal' y va entregando (tiempo, voltaje).

    Esto NO es streaming continuo del ADC -- cada iteración es una captura
    SINGLE completa (arma, espera disparo, descarga), repetida tan rápido
    como el osciloscopio y el USB lo permitan. En la práctica eso da unos
    pocos Hz de actualización, limitados por la espera del disparo y la
    transferencia de la traza completa por USBTMC, no por la velocidad real
    del instrumento. Si tu fenómeno se repite más rápido que eso, vas a
    perderte disparos entre una descarga y la siguiente: no hay buffer de
    eventos intermedios.
    """
    while True:
        yield capturar_canal(osc, canal=canal, esperar_disparo=esperar_disparo)


def graficar_en_vivo(osc, canal='C1', esperar_disparo=True, archivo_salida=None):
    """Modo --streaming: grafica cada captura nueva hasta que se interrumpa con Ctrl+C.

    Import de matplotlib local a esta función a propósito: el resto del
    módulo (conectar, capturar_canal, guardar_csv) solo necesita numpy y
    pyvisa, así que capturar datos sin graficar no debería exigir instalar
    matplotlib.
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError(
            "--streaming necesita matplotlib, que no está instalado. "
            "Instálalo con: pip install matplotlib"
        ) from exc

    fig, ax = plt.subplots()
    linea, = ax.plot([], [], color='#1f6fd6', lw=1.2)
    ax.set_xlabel('tiempo  [s]')
    ax.set_ylabel('voltaje  [V]')
    ax.set_title(f'Captura en vivo · canal {canal}  (Ctrl+C en la terminal para detener)')
    ax.grid(alpha=0.3)
    plt.ion()
    plt.show()

    ultima = None
    n = 0
    try:
        for tiempo, voltaje in stream_capturas(osc, canal=canal, esperar_disparo=esperar_disparo):
            ultima = (tiempo, voltaje)
            n += 1
            linea.set_data(tiempo, voltaje)
            ax.relim()
            ax.autoscale_view()
            ax.set_title(f'Captura en vivo · canal {canal} · disparo #{n} '
                        f'(Ctrl+C en la terminal para detener)')
            fig.canvas.draw_idle()
            fig.canvas.flush_events()
    except KeyboardInterrupt:
        print(f'\nDetenido por el usuario tras {n} captura(s).')
    finally:
        if archivo_salida and ultima is not None:
            guardar_csv(*ultima, archivo_salida)
            print(f'Última traza guardada en: {archivo_salida}')


def parse_args():
    parser = argparse.ArgumentParser(
        description="Captura una traza de un osciloscopio Siglent SDS1000(CNL+) "
                    "por USB y la guarda en un CSV (tiempo[s], voltaje[V]).",
        epilog="Ejemplo: python capturar_osciloscopio.py C1 traza_real.csv"
    )
    parser.add_argument('canal', nargs='?', default='C1',
                        help="canal del osciloscopio a leer (default: C1)")
    parser.add_argument('archivo_salida', nargs='?', default='traza_real.csv',
                        help="archivo CSV de salida (default: traza_real.csv)")
    parser.add_argument('--sin-disparo', action='store_true',
                        help="no armar un disparo SINGLE nuevo; lee la traza que ya "
                            "esté detenida en el osciloscopio")
    parser.add_argument('--streaming', action='store_true',
                        help="modo de captura repetida con gráfico en vivo (Ctrl+C para "
                            "detener); al salir guarda la última traza en archivo_salida")
    return parser.parse_args()


def main():
    args = parse_args()

    osc = conectar()
    print('Conectado:', osc.query('*IDN?').strip())

    if args.streaming:
        graficar_en_vivo(osc, canal=args.canal, esperar_disparo=not args.sin_disparo,
                          archivo_salida=args.archivo_salida)
        return

    tiempo, voltaje = capturar_canal(osc, canal=args.canal,
                                      esperar_disparo=not args.sin_disparo)
    guardar_csv(tiempo, voltaje, args.archivo_salida)

    print(f'{len(voltaje)} puntos capturados en {args.canal}.')
    print(f'Ventana: {tiempo[0]*1e6:.2f} us a {tiempo[-1]*1e6:.2f} us')
    print(f'Guardado en: {args.archivo_salida}')


if __name__ == '__main__':
    main()
