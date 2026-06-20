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
- No soporta otras marcas (Tektronix, Rigol, Keysight...) ni protocolos
  distintos de SCPI/USBTMC — ver [Mejoras futuras](#mejoras-futuras).

## Instalación

### 1. Python y dependencias

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Permisos USB (regla udev)

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

## Cómo funciona el código (para entenderlo, no solo copiarlo)

El script tiene seis funciones, cada una con una responsabilidad acotada:

| Función | Qué hace |
|---|---|
| `conectar()` | Abre la conexión USB con el primer instrumento que encuentre. |
| `armar_y_esperar_disparo(osc)` | Pone el osciloscopio en `SINGLE` y espera a que dispare (`TRMD?` hasta que diga `STOP`). |
| `leer_parametro_numerico(osc, comando)` | Le pregunta al osciloscopio un valor (p. ej. `C1:VDIV?`) e interpreta el prefijo de ingeniería (`u`, `m`, `k`, `M`...) de la respuesta. |
| `descargar_forma_onda(osc, canal)` | Pide la forma de onda cruda en binario (`WF? DAT2`) y extrae los bytes de datos del bloque SCPI. |
| `capturar_canal(osc, canal, esperar_disparo)` | Junta todo: arma el disparo, lee los parámetros de escala, descarga los bytes y los convierte en `(tiempo, voltaje)`. |
| `guardar_csv(tiempo, voltaje, archivo)` | Escribe el CSV final. |

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
- **Promediar varias repeticiones:** envuelve la llamada a `capturar_canal`
  en un `for` y guarda cada traza con un nombre distinto
  (`traza_001.csv`, `traza_002.csv`, ...) para promediarlas después en tu
  análisis — el script no promedia nada por sí mismo, a propósito, para no
  ocultarte cuánto varía tu medición real entre repeticiones.
- **Cambiar el modo de disparo:** si tu señal es continua y no necesitas
  `SINGLE`, usa `--sin-disparo` para leer lo que esté en pantalla en modo
  `RUN`/`AUTO`.
- **Integrarlo a tu propio script:** no necesitas usar `main()` ni la línea
  de comandos — puedes `import` las funciones (`conectar`, `capturar_canal`,
  `guardar_csv`) directamente desde tu propio código Python si tu análisis
  ya vive en un notebook o script.

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
5. **Modo streaming**: en vez de una sola captura `SINGLE` por ejecución,
   un modo que vaya entregando trazas sucesivas en tiempo real (útil para
   experimentos que necesitan monitoreo continuo, no solo un transitorio).

## Créditos

Desarrollado originalmente para el proyecto de gemelo digital de un circuito
RLC, Dirección de Docencia Experimental, Facultad de Ciencias, Universidad
de Chile. Compartido aquí como herramienta de uso general para estudiantes
de licenciatura en Física que necesiten capturar datos de un osciloscopio
Siglent para sus propios proyectos.

Dudas o problemas: Felipe Wasaff (coordinador Física/Matemática, DDE).
