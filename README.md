# Captura de osciloscopio Siglent (USB/SCPI) → CSV

Herramienta para descargar una traza (una curva) desde un osciloscopio
**Siglent serie SDS1000(CNL+)** conectado por USB, y guardarla como un
archivo CSV simple que puedes abrir con Python, Excel, MATLAB o lo que uses
para tu informe.

Nació para un proyecto de gemelo digital de un circuito RLC (Dirección de
Docencia Experimental, Facultad de Ciencias, U. de Chile), pero **el script
no tiene nada específico de ese experimento**: captura voltaje en función
del tiempo, sin importar qué generó esa señal. Si tu proyecto necesita
"sacar una curva del osciloscopio a una planilla o a Python", probablemente
te sirve tal cual.

> **Manual en PDF:** [`manual/manual_captura_osciloscopio.pdf`](manual/manual_captura_osciloscopio.pdf)
> tiene esta misma información en formato imprimible, con tabla de solución
> de problemas y checklist previo a capturar. Este README es la referencia
> rápida; el manual es la versión para imprimir o consultar paso a paso.

## Inicio rápido

```bash
git clone https://github.com/fwasaff/captura_osciloscopio_siglent.git
cd captura_osciloscopio_siglent
python3 -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**¿Todavía no tienes el osciloscopio a mano?** Prueba primero el modo demo
— simula el instrumento con una señal sintética, sin hardware ni VISA:

```bash
python capturar_osciloscopio.py --demo
python capturar_osciloscopio.py --demo --streaming   # gráfico en vivo, Ctrl+C para detener
```

Esto te deja practicar el flujo completo (instalar, capturar, leer el CSV,
ver el gráfico en vivo) antes del día de laboratorio. La consola avisa
explícitamente que los datos son sintéticos, para que nunca se confundan
con una medición real.

Cuando tengas el instrumento real: si usas **Windows o macOS**, instala
además [NI-VISA](https://www.ni.com/es/support/downloads/drivers/download.ni-visa.html)
(gratis) y listo — sin pasos adicionales de permisos.
Si usas **Linux**, hace falta un paso más (una regla de permisos USB): ver
[Instalación → Linux](#linux) más abajo, es copiar y pegar cinco líneas.

```bash
python capturar_osciloscopio.py          # una captura -> traza_real.csv
python capturar_osciloscopio.py --streaming   # gráfico en vivo, Ctrl+C para detener
```

Si algo falla, la sección [Solución de problemas](#solución-de-problemas-comunes)
de este README (o del manual en PDF) cubre los errores más comunes con su
causa y solución.

## ¿Para qué proyectos te sirve esto?

Cualquier experimento de laboratorio donde midas una señal transitoria con
el osciloscopio y necesites los datos crudos para analizarlos después:

- Carga/descarga de un capacitor (RC) o de un circuito RLC.
- Respuesta de un sensor óptico (foto-puerta, fotodiodo) ante un evento.
- Señal de un acelerómetro o micrófono conectado a un canal del osciloscopio.
- Cualquier transitorio de un escalón, pulso o disparo único que el
  osciloscopio pueda capturar y mostrar en pantalla.

Si tu señal es periódica y solo necesitas frecuencia/amplitud, probablemente
te baste con leerla directamente en el panel del instrumento — esta
herramienta tiene sentido cuando necesitas los **puntos crudos** para
ajustar un modelo, hacer un gráfico con tu propio estilo, o procesarla con
código.

## Alcance actual

- Soporta osciloscopios **Siglent serie SDS1000(CNL+)** (probado en un
  SDS1102CNL+) que hablan el protocolo SCPI sobre USBTMC.
- Captura **un canal a la vez** (`C1`, `C2`, etc., según cuántos canales
  tenga tu modelo).
- Pensado para **disparo único** (`SINGLE`): arma el disparo, espera a que
  el osciloscopio capture, y descarga esa traza. También puede leer una
  traza que ya esté detenida en pantalla (`--sin-disparo`).
- **Modo `--streaming`:** repite la captura y grafica en vivo (ver
  [Captura en vivo](#captura-en-vivo---streaming)). No es streaming continuo
  del ADC, sino capturas `SINGLE` sucesivas tan rápido como el USB lo
  permita — ver el detalle de esa limitación más abajo.
- **Modo `--demo`:** simula el osciloscopio con una señal sintética, sin
  hardware ni VISA instalado — para practicar el flujo completo antes de
  tener el instrumento real (ver [Inicio rápido](#inicio-rápido)).
- **`--promediar N`:** captura N trazas y guarda su promedio con
  incertidumbre (ver [Promediar capturas](#promediar-capturas---promediar)).
- **`--log-estadisticas ARCHIVO`:** registra estadísticas de cada captura en
  un CSV aparte, que crece entre sesiones (ver
  [Log de estadísticas](#log-de-estadísticas---log-estadisticas)).
- **`--fft`** (con `--streaming`): agrega un panel con el espectro de
  frecuencias de cada captura, para diagnosticar ruido de alta frecuencia.
- No soporta otras marcas (Tektronix, Rigol, Keysight...) ni protocolos
  distintos de SCPI/USBTMC — ver [Mejoras futuras](#mejoras-futuras).

## Instalación

El script usa el VISA del sistema si está instalado (Windows/macOS), o cae
automáticamente al backend puro de Python `pyvisa-py` si no hay ninguno
instalado (el caso típico en Linux). Por eso los pasos difieren según tu
sistema operativo — el código es el mismo, solo cambia cómo el sistema le da
acceso al puerto USB.

### 1. Python y dependencias (todos los sistemas)

```bash
python3 -m venv venv
source venv/bin/activate          # en Windows (cmd o PowerShell): venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Acceso al instrumento

#### Windows / macOS

Instala **[NI-VISA](https://www.ni.com/es/support/downloads/drivers/download.ni-visa.html)**
(gratis, de National Instruments) o, alternativamente, **Keysight IO
Libraries Suite**. El instalador deja todo configurado: controlador USB,
permisos, reconocimiento del instrumento. No hace falta ningún paso de
permisos adicional — `pyvisa.ResourceManager()` encuentra el instrumento
automáticamente una vez que NI-VISA está instalado.

#### Linux

Linux no deja acceder a dispositivos USB sin privilegios de administrador a
menos que exista una regla que lo autorice explícitamente. Sin este paso,
vas a ver un error de permisos al conectar.

```bash
sudo cp 99-usbtmc-siglent.rules /etc/udev/rules.d/
sudo groupadd -f usbtmc
sudo usermod -aG usbtmc "$USER"
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Después de esto, **cierra sesión y vuelve a entrar** (o reinicia) para que
el cambio de grupo tenga efecto, y reconecta el cable USB del osciloscopio.

Si tu osciloscopio no es reconocido, ejecuta `lsusb` con el instrumento
conectado y busca su `idVendor`; si no es `f4ec`, ajústalo en el archivo
`.rules` antes de copiarlo.

### 3. Verificar la conexión

Con el osciloscopio encendido y el cable USB conectado:

```bash
python capturar_osciloscopio.py --help
```

Si ves el mensaje de ayuda sin errores, las dependencias están bien
instaladas. El siguiente paso ya requiere el instrumento físico conectado.

## Uso

```bash
# Captura el canal 1, dispara en SINGLE, guarda en traza_real.csv (todo por defecto)
python capturar_osciloscopio.py

# Especificar canal y archivo de salida
python capturar_osciloscopio.py C2 mi_experimento.csv

# Leer una traza que ya tienes detenida en pantalla, sin rearmar el disparo
python capturar_osciloscopio.py C1 traza.csv --sin-disparo
```

Salida esperada en la terminal:

```
Conectado: Siglent Technologies,SDS1102CNL+,...
20480 puntos capturados en C1.
Ventana: -20.48 us a 184.30 us
Guardado en: traza_real.csv
```

### Formato del archivo de salida

Un CSV de dos columnas, con encabezado:

```
tiempo[s],voltaje[V]
-2.048000000e-05,-1.063000000e+00
-2.047000000e-05,-1.061000000e+00
...
```

El instante `t=0` corresponde al trigger del osciloscopio, **no**
necesariamente al inicio "real" de tu fenómeno físico — eso depende de tu
experimento. En `ejemplos/traza_ejemplo.csv` hay un archivo de muestra
(datos **sintéticos**, generados para ilustrar el formato, no una medición
real) para que veas la forma del archivo sin necesitar el instrumento a
mano.

## Captura en vivo (`--streaming`)

```bash
python capturar_osciloscopio.py --streaming
python capturar_osciloscopio.py C2 ultima_traza.csv --streaming
```

Abre una ventana con un gráfico que se va actualizando con cada captura
nueva (arma disparo → espera → descarga → grafica → repite), más un panel
lateral con estadísticas de la traza actual (mín./máx./pico a pico/RMS,
número de puntos, ventana de tiempo, frecuencia de actualización). Presiona
`Ctrl+C` en la terminal para detener; al salir, guarda la **última** traza
capturada en `archivo_salida`.

Los ejes no se reencuadran en cada captura — eso se ve nervioso si el ruido
hace variar un poco el mínimo o máximo de cada traza. El rango se fija con
la primera captura y solo se **expande** si una traza nueva no entra; nunca
se achica. El resultado es una ventana estable, no una que salta de escala
todo el tiempo.

> **Qué es y qué no es esto.** El osciloscopio se comunica por
> SCPI/USBTMC, un protocolo de pregunta-respuesta ("dame lo que hay en
> pantalla ahora"), no un canal de streaming continuo del ADC. Cada
> actualización del gráfico es una captura `SINGLE` completa, repetida tan
> rápido como el osciloscopio y el USB lo permitan — en la práctica, pocos
> Hz, limitados por la espera del disparo y la transferencia de la traza
> completa, no por la velocidad real del instrumento. Si tu fenómeno se
> repite más rápido que eso, vas a perderte disparos entre una descarga y
> la siguiente: no hay buffer de eventos intermedios. Para eso, este modo
> sirve para *monitorear* (ajustar el trigger, ver que la señal se vea
> bien antes de la captura "buena"), no para no perderse ningún evento de
> una serie rápida.

Requiere `matplotlib` (no es necesario para el resto del script — ver
`requirements.txt`).

### Espectro de frecuencias (`--fft`)

```bash
python capturar_osciloscopio.py --streaming --fft
```

Agrega un segundo panel con el espectro de amplitud (FFT) de cada captura,
en escala log-log. Útil para diagnosticar **ruido de alta frecuencia**:
interferencia de fuentes conmutadas, RF, o ver directamente el contenido
espectral del propio transitorio (p. ej. la frecuencia natural de un RLC).

> **Lo que NO sirve para ver:** ruido de red (50/60 Hz). La resolución en
> frecuencia es $1/\text{ventana}$ — con una ventana típica de pocos cientos
> de microsegundos, eso son varios **kHz** por punto, demasiado grueso para
> resolver una frecuencia de 50 Hz. Para eso se necesitaría una ventana de
> captura mucho más larga (decenas de milisegundos como mínimo), que este
> script no controla — la ventana depende de la base de tiempo configurada
> en el osciloscopio.

## Promediar capturas (`--promediar`)

```bash
python capturar_osciloscopio.py --promediar 20 promedio.csv
```

Captura N trazas y guarda su **promedio punto a punto**, con la desviación
estándar como tercera columna (`incertidumbre[V]`) — el ruido aleatorio cae
como $1/\sqrt{N}$ al promediar, el resultado clásico de mediciones repetidas
que se enseña en cualquier curso de física experimental. El resumen en
consola incluye la reducción de ruido esperada para el N elegido.

No se combina con `--streaming` (son dos modos distintos: uno repite y
monitorea, el otro repite y promedia). Si pasas ambos, el script se detiene
con un mensaje de error claro en vez de hacer algo ambiguo.

## Log de estadísticas (`--log-estadisticas`)

```bash
python capturar_osciloscopio.py --log-estadisticas sesion.csv
python capturar_osciloscopio.py --streaming --log-estadisticas sesion.csv
```

Agrega una fila (`disparo, timestamp, V_min, V_max, V_pp, V_rms, V_med`) por
cada captura al archivo indicado. Si el archivo ya existe, sigue agregando
filas — es un log que **crece entre sesiones**, no se sobrescribe. Con
`--streaming` se agrega una fila por disparo; sin `--streaming`, una fila
por ejecución del script.

Útil para responder, con tus propios datos y herramientas, preguntas como
"¿qué tan repetible fue mi medición?" o "¿mi montaje derivó durante la
sesión?" — el script solo registra los números, no decide qué significan.

## Cómo funciona el código (para entenderlo, no solo copiarlo)

El script tiene trece funciones, cada una con una responsabilidad acotada:

| Función | Qué hace |
|---|---|
| `conectar()` | Abre la conexión USB con el primer instrumento que encuentre, usando VISA del sistema si existe (Windows/macOS) o `pyvisa-py` si no (Linux). |
| `armar_y_esperar_disparo(osc)` | Pone el osciloscopio en `SINGLE` y espera a que dispare (`TRMD?` hasta que diga `STOP`). |
| `leer_parametro_numerico(osc, comando)` | Le pregunta al osciloscopio un valor (p. ej. `C1:VDIV?`) e interpreta el prefijo de ingeniería (`u`, `m`, `k`, `M`...) de la respuesta. |
| `descargar_forma_onda(osc, canal)` | Pide la forma de onda cruda en binario (`WF? DAT2`) y extrae los bytes de datos del bloque SCPI. |
| `capturar_canal(osc, canal, esperar_disparo)` | Junta todo: arma el disparo, lee los parámetros de escala, descarga los bytes y los convierte en `(tiempo, voltaje)`. |
| `guardar_csv(tiempo, voltaje, archivo)` | Escribe el CSV de una captura. |
| `promediar_capturas(osc, canal, esperar_disparo, n)` | Captura n trazas y devuelve su promedio y desviación estándar; implementa `--promediar`. |
| `guardar_csv_promedio(tiempo, voltaje_prom, voltaje_std, archivo)` | Escribe el CSV de un promedio, con la incertidumbre como tercera columna. |
| `registrar_estadisticas(archivo_log, disparo, tiempo, voltaje)` | Agrega una fila de estadísticas al log (crea el encabezado solo si el archivo es nuevo); implementa `--log-estadisticas`. |
| `calcular_fft(tiempo, voltaje)` | Espectro de amplitud (FFT) de una traza, sin el nivel DC; implementa el panel de `--fft`. |
| `stream_capturas(osc, canal, esperar_disparo)` | Generador (`yield`): repite `capturar_canal` indefinidamente, una traza por iteración. |
| `graficar_en_vivo(osc, canal, esperar_disparo, archivo_salida, archivo_log, mostrar_fft)` | Consume `stream_capturas` y actualiza el gráfico (panel de estadísticas, ejes estables, FFT opcional) en cada traza nueva; implementa `--streaming`. |
| `_OsciloscopioSimulado` | Implementa `query`/`write`/`read_raw` con una señal sintética en vez de hardware real; implementa `--demo`. |

Los detalles que vale la pena entender si vas a tocar el código:

- **Los datos llegan como bytes, no como voltios.** El osciloscopio manda
  códigos enteros de 8 bits (`np.int8`, rango $-128$ a $127$); la conversión
  a voltios usa la escala vertical (`VDIV`) y el offset (`OFST`) que el
  propio instrumento reporta: `voltaje = codigo * (VDIV/25) - OFST`. El
  `25` es una constante del protocolo Siglent (un código de pantalla
  completa equivale a 25 divisiones verticales).
- **El eje de tiempo se reconstruye, no se mide directamente.** Se usa la
  tasa de muestreo (`SARA`) para el paso entre puntos, y el retardo de
  trigger (`TRDL`) más la escala horizontal (`TDIV`) para ubicar el cero.
  `GRID_HORIZONTAL = 14` son las divisiones horizontales de pantalla de la
  serie SDS1000 — si tu modelo tiene otra cantidad de divisiones, ese es el
  valor a cambiar.
- **El bloque binario tiene un formato propio del protocolo SCPI:** la
  respuesta de `WF? DAT2` trae un marcador `#9` seguido de 9 dígitos que
  indican cuántos bytes de datos vienen a continuación. `descargar_forma_onda`
  busca ese marcador y recorta exactamente esa cantidad de bytes.

## Cómo adaptarlo a tu propio experimento

- **Capturar dos canales:** llama a `capturar_canal(osc, canal='C1')` y
  `capturar_canal(osc, canal='C2')` por separado (el osciloscopio ya tiene
  ambos canales disparados juntos si comparten el mismo trigger), y junta
  los resultados en un CSV de tres columnas.
- **Promediar varias repeticiones:** usa `--promediar N` (ver
  [Promediar capturas](#promediar-capturas---promediar)) si quieres el
  promedio con incertidumbre. Si en cambio quieres conservar cada traza
  individual sin promediar (para ver tú mismo cuánto varía cada repetición,
  no solo el resultado final), envuelve `capturar_canal` en un `for` y
  guarda cada una con un nombre distinto (`traza_001.csv`,
  `traza_002.csv`, ...).
- **Cambiar el modo de disparo:** si tu señal es continua y no necesitas
  `SINGLE`, usa `--sin-disparo` para leer lo que esté en pantalla en modo
  `RUN`/`AUTO`.
- **Integrarlo a tu propio script:** no necesitas usar `main()` ni la línea
  de comandos — puedes `import` las funciones (`conectar`, `capturar_canal`,
  `guardar_csv`) directamente desde tu propio código Python si tu análisis
  ya vive en un notebook o script.
- **Procesar cada captura en vivo, no solo graficarla:** `stream_capturas`
  es un generador genérico — puedes consumirlo con tu propio `for` en vez
  de `graficar_en_vivo` para, por ejemplo, calcular en línea el RMS de cada
  traza o guardarlas todas (no solo la última) a medida que llegan.

## Limitaciones actuales

- Un solo canal por llamada (sin soporte nativo para captura simultánea
  multi-canal en una sola descarga).
- Solo probado contra Siglent SDS1000CNL+; otros modelos Siglent deberían
  funcionar si comparten el mismo dialecto SCPI, pero no está verificado.
- Si el cable USB se desconecta a mitad de una captura, no hay
  reintentos automáticos — hay que volver a ejecutar el script.
- No guarda metadatos del osciloscopio (escala, offset, modelo) en el CSV
  de salida, solo los puntos ya convertidos a voltios y segundos.

## Mejoras futuras

En orden sugerido de prioridad/costo:

1. **Guardar metadata en el CSV** (VDIV, OFST, TDIV, SARA, modelo del
   instrumento) como comentario en el encabezado, para trazabilidad de cada
   medición sin tener que anotarla a mano.
2. **Captura multi-canal en una sola llamada**, devolviendo un CSV con una
   columna de tiempo y una columna de voltaje por canal activo.
3. **Reintento automático de conexión** si el USB se desconecta o el
   instrumento no responde a tiempo.
4. **Soporte para otros fabricantes** (Rigol, Tektronix) abstrayendo las
   partes específicas del protocolo Siglent detrás de una interfaz común,
   de modo que cambiar de instrumento no signifique reescribir el script.
5. **Guardar cada captura del modo `--streaming`**, no solo la última (hoy
   `graficar_en_vivo` descarta todas las trazas intermedias al salir) ---
   útil si quieres revisar después cómo varió la señal mientras ajustabas
   el experimento.

## Créditos

Desarrollado originalmente para el proyecto de gemelo digital de un circuito
RLC, Dirección de Docencia Experimental, Facultad de Ciencias, Universidad
de Chile. Compartido aquí como herramienta de uso general para estudiantes
de licenciatura en Física que necesiten capturar datos de un osciloscopio
Siglent para sus propios proyectos.

Dudas o problemas: Felipe Wasaff (coordinador Física/Matemática, DDE).
