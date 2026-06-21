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
    python capturar_osciloscopio.py [-h] [canal] [archivo_salida] [--sin-disparo] [--streaming] [--demo]
    python capturar_osciloscopio.py C1 traza_real.csv
    python capturar_osciloscopio.py --streaming
    python capturar_osciloscopio.py --demo
    python capturar_osciloscopio.py --help

--demo simula el osciloscopio con una señal sintética (un escalón con ruido),
sin necesitar el instrumento real conectado ni VISA instalado. Sirve para
practicar el flujo completo -- captura, --streaming, lectura del CSV -- antes
de tener acceso al instrumento de verdad. Los datos generados NO son una
medición real; el script lo deja explícito en la salida por consola.

Por defecto arma un disparo SINGLE y espera a que el osciloscopio capture.
Si el osciloscopio ya está detenido con la traza que quieres (p. ej. la
armaste manualmente desde el panel), usa --sin-disparo para leerla tal cual.

--streaming abre un gráfico que se va actualizando con cada captura nueva
(Ctrl+C para detener). No es streaming continuo del ADC -- cada actualización
es una captura SINGLE completa, repetida tan rápido como el osciloscopio y el
USB lo permitan (en la práctica, unos pocos Hz). Si tu fenómeno se repite más
rápido que eso, vas a perderte disparos entre una descarga y la siguiente.

--promediar N captura N trazas y guarda su promedio con la desviación
estándar como incertidumbre (tercera columna del CSV) -- el ruido aleatorio
cae como 1/sqrt(N). No se combina con --streaming.

--log-estadisticas ARCHIVO agrega una fila (V_min/V_max/V_pp/V_rms/V_med) por
cada captura a un CSV aparte -- con --streaming, una fila por disparo, útil
para revisar después la repetibilidad o deriva de una sesión completa.

--fft (solo con --streaming) agrega un panel con el espectro de frecuencias
de cada captura. Sirve para diagnosticar ruido de ALTA frecuencia (fuentes
conmutadas, interferencia RF, oscilación propia de la señal) -- NO para
ruido de red (50/60 Hz): con una ventana de pocos cientos de microsegundos,
la resolución en frecuencia es de varios kHz, demasiado gruesa para eso.

Referencia: Siglent Digital Oscilloscopes Programming Guide, secciones
WAVEFORM (WF?) y WAVEFORM_SETUP (WFSU).
"""

import argparse
import csv
import os
import re
import time

import numpy as np
import pyvisa

GRID_HORIZONTAL = 14  # divisiones horizontales de pantalla en la serie SDS1000

_PREFIJOS_SI = {'p': 1e-12, 'n': 1e-9, 'u': 1e-6, 'µ': 1e-6, 'm': 1e-3,
                'k': 1e3, 'K': 1e3, 'M': 1e6, 'G': 1e9}
_RE_NUMERO = re.compile(r'^([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s*(.*)$')


_N_MUESTRAS_DEMO = 20480
_VDIV_DEMO = 0.5      # V/div
_OFST_DEMO = 0.0      # V
_TDIV_DEMO = 20e-6    # s/div
_TRDL_DEMO = 40e-6    # s (retardo de trigger)
_SARA_DEMO = 1e8      # muestras/s (100 MSa/s, como el SDS1102CNL+ real)


def _generar_codigos_demo(rng):
    """Genera una señal sintética (un escalón con ruido) y la codifica como
    int8, igual que lo haría el osciloscopio real, usando la escala VDIV/OFST
    de --demo. NO es una medición real -- solo sirve para practicar el flujo.
    """
    dt = 1.0 / _SARA_DEMO
    t0 = _TRDL_DEMO - (_TDIV_DEMO * GRID_HORIZONTAL / 2.0)
    t = t0 + dt * np.arange(_N_MUESTRAS_DEMO)

    baseline = -0.9
    amplitud = 1.9 + 0.1 * rng.standard_normal()   # un poco de variación entre capturas
    tau = 15e-6 * (1.0 + 0.1 * rng.standard_normal())
    voltaje = np.where(t < 0, baseline,
                        baseline + amplitud * (1.0 - np.exp(-t / tau)))
    voltaje += rng.normal(0.0, 0.01, t.shape)  # ruido de medición, ~10 mV

    codigos = np.round((voltaje + _OFST_DEMO) / (_VDIV_DEMO / 25.0))
    codigos = np.clip(codigos, -128, 127).astype(np.int8)
    return codigos


class _OsciloscopioSimulado:
    """Implementa lo mínimo de la interfaz de pyvisa que el resto del módulo
    necesita (query, write, read_raw), para poder ejercitar el mismo camino
    de código que con el instrumento real -- sin tener uno conectado. Usado
    por --demo.
    """

    def __init__(self):
        self._rng = np.random.default_rng()

    def query(self, comando):
        comando = comando.strip().upper()
        if comando == '*IDN?':
            return 'Siglent Technologies,SDS1102CNL+ (SIMULADO),DEMO,1.0.0'
        if comando == 'TRMD?':
            return 'TRMD STOP'
        if comando.endswith(':VDIV?'):
            return f'VDIV {_VDIV_DEMO * 1e3:.1f}mV'
        if comando.endswith(':OFST?'):
            return f'OFST {_OFST_DEMO:.2f}V'
        if comando == 'TDIV?':
            return f'TDIV {_TDIV_DEMO * 1e6:.1f}us'
        if comando == 'TRDL?':
            return f'TRDL {_TRDL_DEMO * 1e6:.1f}us'
        if comando == 'SARA?':
            return f'SARA {_SARA_DEMO / 1e6:.1f}MSa'
        raise ValueError(f"Comando SCPI no soportado en modo demo: '{comando}'")

    def write(self, comando):
        pass  # en modo demo no hay nada que enviar a un instrumento real

    def read_raw(self):
        time.sleep(0.2)  # simula la latencia real de armar+transferir una captura
        codigos = _generar_codigos_demo(self._rng)
        return f'#9{len(codigos):09d}'.encode() + codigos.tobytes()


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


def conectar(demo=False):
    """Abre el primer instrumento USBTMC que se encuentre, o un osciloscopio
    simulado si demo=True (ver --demo) -- útil para practicar el flujo
    completo sin tener el instrumento real a mano.

    El error de permisos es, en la práctica, el motivo más común por el que
    esto falla la primera vez que un/a estudiante lo prueba en un computador
    nuevo -- de ahí el mensaje explícito en vez de dejar pasar la traza cruda
    de Python.
    """
    if demo:
        return _OsciloscopioSimulado()

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


def promediar_capturas(osc, canal='C1', esperar_disparo=True, n=10):
    """Captura n trazas y devuelve su promedio punto a punto, con la
    desviación estándar como incertidumbre.

    El ruido aleatorio de una medición repetida n veces cae como 1/sqrt(n)
    al promediar -- el resultado clásico de estadística de mediciones
    repetidas que cualquier curso de física experimental enseña. Se usa
    ddof=1 (desviación estándar muestral) porque n es una muestra, no la
    población completa de posibles mediciones.
    """
    trazas = []
    tiempo_ref = None
    for _ in range(n):
        tiempo, voltaje = capturar_canal(osc, canal=canal, esperar_disparo=esperar_disparo)
        if tiempo_ref is None:
            tiempo_ref = tiempo
        trazas.append(voltaje)
    matriz = np.vstack(trazas)
    voltaje_prom = matriz.mean(axis=0)
    voltaje_std = matriz.std(axis=0, ddof=1) if n > 1 else np.zeros_like(voltaje_prom)
    return tiempo_ref, voltaje_prom, voltaje_std


def guardar_csv_promedio(tiempo, voltaje_prom, voltaje_std, archivo_salida):
    """Guarda el promedio de varias capturas (ver --promediar) con su
    incertidumbre (desviación estándar) como tercera columna.
    """
    datos = np.column_stack([tiempo, voltaje_prom, voltaje_std])
    np.savetxt(archivo_salida, datos, delimiter=',',
               header='tiempo[s],voltaje[V],incertidumbre[V]',
               comments='', fmt='%.9e')


def _estadisticas(voltaje):
    vmin, vmax = float(voltaje.min()), float(voltaje.max())
    return {
        'V_min': vmin, 'V_max': vmax, 'V_pp': vmax - vmin,
        'V_rms': float(np.sqrt(np.mean(voltaje ** 2))),
        'V_med': float(voltaje.mean()),
    }


def registrar_estadisticas(archivo_log, disparo, tiempo, voltaje):
    """Agrega una fila de estadísticas (una por captura) a archivo_log.

    Si el archivo ya existe, sigue agregando filas -- un log que crece
    entre sesiones, para que el/la estudiante pueda analizar después, con
    sus propias herramientas, qué tan repetible fue su medición o si hubo
    deriva durante la sesión. Esta función no decide qué significa esa
    variación, solo la registra.
    """
    nuevo = not os.path.exists(archivo_log)
    est = _estadisticas(voltaje)
    with open(archivo_log, 'a', newline='') as f:
        writer = csv.writer(f)
        if nuevo:
            writer.writerow(['disparo', 'timestamp', 'V_min[V]', 'V_max[V]',
                            'V_pp[V]', 'V_rms[V]', 'V_med[V]'])
        writer.writerow([disparo, f'{time.time():.3f}', f"{est['V_min']:.6f}",
                        f"{est['V_max']:.6f}", f"{est['V_pp']:.6f}",
                        f"{est['V_rms']:.6f}", f"{est['V_med']:.6f}"])


def calcular_fft(tiempo, voltaje):
    """Espectro de amplitud de la traza (FFT), quitando el nivel DC.

    La resolución en frecuencia es 1/ventana: con una ventana de pocos
    cientos de microsegundos (típico de un transitorio rápido), eso son
    varios kHz por punto -- demasiado grueso para resolver ruido de red
    (50/60 Hz). Sirve para diagnosticar contenido de ALTA frecuencia: ruido
    de fuentes conmutadas, interferencia RF, o el propio contenido espectral
    del transitorio (p. ej. la frecuencia natural de un RLC).
    """
    dt = tiempo[1] - tiempo[0]
    v = voltaje - voltaje.mean()
    espectro = np.abs(np.fft.rfft(v))
    frecuencia = np.fft.rfftfreq(len(v), d=dt)
    return frecuencia[1:], espectro[1:]  # se descarta el bin DC (freq=0): no se ve en escala log


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


def graficar_en_vivo(osc, canal='C1', esperar_disparo=True, archivo_salida=None,
                      archivo_log=None, mostrar_fft=False):
    """Modo --streaming: grafica cada captura nueva hasta que se interrumpa con Ctrl+C.

    Import de matplotlib local a esta función a propósito: el resto del
    módulo (conectar, capturar_canal, guardar_csv) solo necesita numpy y
    pyvisa, así que capturar datos sin graficar no debería exigir instalar
    matplotlib.

    Los ejes del gráfico de tiempo NO se reencuadran en cada captura (eso se
    ve nervioso si el ruido hace variar un poco el mínimo/máximo de cada
    traza): el rango se fija con la primera captura y solo se EXPANDE si una
    traza nueva no entra -- nunca se achica. El panel lateral muestra
    estadísticas de la traza actual, en el mismo estilo del panel de texto
    de gemelo.py. El panel de FFT (si mostrar_fft=True) sí se reencuadra
    cada vez -- es una vista de exploración, no de lectura estable.
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise ImportError(
            "--streaming necesita matplotlib, que no está instalado. "
            "Instálalo con: pip install matplotlib"
        ) from exc

    fig = plt.figure(figsize=(10, 7.5 if mostrar_fft else 5.5))
    fig.canvas.manager.set_window_title(f'Captura en vivo - canal {canal}')

    if mostrar_fft:
        ax = fig.add_axes([0.08, 0.57, 0.62, 0.36])
        ax_fft = fig.add_axes([0.08, 0.10, 0.62, 0.36])
        linea_fft, = ax_fft.plot([], [], color='#d62728', lw=1.0)
        ax_fft.set_xlabel('frecuencia  [Hz]')
        ax_fft.set_ylabel('magnitud  [u.a.]')
        ax_fft.set_xscale('log')
        ax_fft.set_yscale('log')
        ax_fft.grid(alpha=0.3, which='both')
    else:
        ax = fig.add_axes([0.08, 0.12, 0.62, 0.80])
        ax_fft = None

    linea, = ax.plot([], [], color='#1f6fd6', lw=1.2)
    ax.set_xlabel('tiempo  [s]')
    ax.set_ylabel('voltaje  [V]')
    ax.set_title(f'Canal {canal}  ·  Ctrl+C en la terminal para detener')
    ax.grid(alpha=0.3)

    txt = fig.text(0.74, 0.92 if mostrar_fft else 0.90, '', fontsize=10, va='top',
                    family='monospace',
                    bbox=dict(boxstyle='round', fc='#f4f4f0', ec='#cccccc'))
    plt.ion()
    plt.show()

    limite_x, limite_y = None, None

    def _actualizar_limites(tiempo, voltaje):
        nonlocal limite_x, limite_y
        margen = max((voltaje.max() - voltaje.min()) * 0.1, 1e-3)
        ymin, ymax = voltaje.min() - margen, voltaje.max() + margen
        if limite_x is None:
            limite_x = [float(tiempo[0]), float(tiempo[-1])]
        if limite_y is None:
            limite_y = [float(ymin), float(ymax)]
        else:
            limite_y[0] = min(limite_y[0], float(ymin))
            limite_y[1] = max(limite_y[1], float(ymax))
        ax.set_xlim(*limite_x)
        ax.set_ylim(*limite_y)

    ultima = None
    n = 0
    t_anterior = None
    try:
        for tiempo, voltaje in stream_capturas(osc, canal=canal, esperar_disparo=esperar_disparo):
            ultima = (tiempo, voltaje)
            n += 1
            ahora = time.time()
            hz = 1.0 / (ahora - t_anterior) if t_anterior else 0.0
            t_anterior = ahora

            linea.set_data(tiempo, voltaje)
            _actualizar_limites(tiempo, voltaje)

            if ax_fft is not None:
                frecuencia, espectro = calcular_fft(tiempo, voltaje)
                linea_fft.set_data(frecuencia, espectro)
                ax_fft.relim()
                ax_fft.autoscale_view()

            if archivo_log:
                registrar_estadisticas(archivo_log, n, tiempo, voltaje)

            txt.set_text(
                f"CAPTURA EN VIVO\n"
                f"Canal:    {canal}\n"
                f"Disparo:  #{n}\n"
                f"\n"
                f"V_min  = {voltaje.min():+7.3f} V\n"
                f"V_max  = {voltaje.max():+7.3f} V\n"
                f"V_pp   = {voltaje.max() - voltaje.min():7.3f} V\n"
                f"V_rms  = {np.sqrt(np.mean(voltaje ** 2)):7.3f} V\n"
                f"V_med  = {voltaje.mean():+7.3f} V\n"
                f"\n"
                f"n = {len(voltaje)} puntos\n"
                f"ventana = {(tiempo[-1] - tiempo[0]) * 1e6:.1f} us\n"
                f"\n"
                f"actualiz. = {hz:.1f} Hz"
            )
            fig.canvas.draw_idle()
            fig.canvas.flush_events()
    except KeyboardInterrupt:
        print(f'\nDetenido por el usuario tras {n} captura(s).')
    finally:
        if archivo_salida and ultima is not None:
            guardar_csv(*ultima, archivo_salida)
            print(f'Última traza guardada en: {archivo_salida}')
        if archivo_log:
            print(f'Estadísticas de la sesión guardadas en: {archivo_log}')


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
    parser.add_argument('--demo', action='store_true',
                        help="simula el osciloscopio con una señal sintética, sin "
                            "necesitar el instrumento real ni VISA instalado (para "
                            "practicar el flujo completo)")
    parser.add_argument('--promediar', type=int, default=1, metavar='N',
                        help="captura N trazas y guarda su promedio con incertidumbre "
                            "(desviación estándar) como tercera columna; no se combina "
                            "con --streaming")
    parser.add_argument('--log-estadisticas', metavar='ARCHIVO', default=None,
                        help="agrega una fila de estadísticas (V_min/V_max/V_pp/V_rms/"
                            "V_med) por cada captura a ARCHIVO; con --streaming, una "
                            "fila por disparo")
    parser.add_argument('--fft', action='store_true',
                        help="agrega un panel con el espectro de frecuencias de cada "
                            "captura (solo tiene efecto con --streaming)")

    args = parser.parse_args()
    if args.promediar < 1:
        parser.error("--promediar debe ser un entero positivo")
    if args.promediar > 1 and args.streaming:
        parser.error("--promediar no se puede combinar con --streaming "
                    "(ver README, sección Captura en vivo)")
    return args


def main():
    args = parse_args()

    osc = conectar(demo=args.demo)
    print('Conectado:', osc.query('*IDN?').strip())
    if args.demo:
        print('(Modo demo: esto NO es una medición real, es una señal sintética '
              'para practicar.)')

    if args.streaming:
        if args.fft:
            print('(--fft activado: panel de espectro de frecuencias agregado.)')
        graficar_en_vivo(osc, canal=args.canal, esperar_disparo=not args.sin_disparo,
                          archivo_salida=args.archivo_salida,
                          archivo_log=args.log_estadisticas, mostrar_fft=args.fft)
        return

    if args.fft:
        print('(--fft solo tiene efecto junto con --streaming; se ignora aquí.)')

    if args.promediar > 1:
        tiempo, voltaje_prom, voltaje_std = promediar_capturas(
            osc, canal=args.canal, esperar_disparo=not args.sin_disparo, n=args.promediar)
        guardar_csv_promedio(tiempo, voltaje_prom, voltaje_std, args.archivo_salida)
        if args.log_estadisticas:
            registrar_estadisticas(args.log_estadisticas, args.promediar, tiempo, voltaje_prom)

        incertidumbre_tipica = np.sqrt(np.mean(voltaje_std ** 2))
        print(f'{args.promediar} capturas promediadas en {args.canal}.')
        print(f'Ventana: {tiempo[0]*1e6:.2f} us a {tiempo[-1]*1e6:.2f} us')
        print(f'Incertidumbre típica: {incertidumbre_tipica * 1e3:.2f} mV '
            f'(reducción esperada vs. una sola traza: ~sqrt({args.promediar}) '
            f'= {np.sqrt(args.promediar):.1f}x)')
        print(f'Guardado en: {args.archivo_salida}')
        return

    tiempo, voltaje = capturar_canal(osc, canal=args.canal,
                                      esperar_disparo=not args.sin_disparo)
    guardar_csv(tiempo, voltaje, args.archivo_salida)
    if args.log_estadisticas:
        registrar_estadisticas(args.log_estadisticas, 1, tiempo, voltaje)

    print(f'{len(voltaje)} puntos capturados en {args.canal}.')
    print(f'Ventana: {tiempo[0]*1e6:.2f} us a {tiempo[-1]*1e6:.2f} us')
    print(f'Guardado en: {args.archivo_salida}')


if __name__ == '__main__':
    main()
