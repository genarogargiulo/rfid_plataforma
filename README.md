# Plataforma RFID — FPT Córdoba

Plataforma multi-reader para trazabilidad de pallets vía RFID. Se conecta
a N readers Impinj (u otros compatibles LLRP), decodifica cada lectura, y
la guarda en SQL Server para que el cliente (FPT) la explote directamente
con consultas SQL o Power BI, sin pasar por la aplicación.

Basada en los requerimientos relevados con el cliente:
- Solución **standalone** (no integra con el WMS Click Reply).
- Solo registra **la pasada** del tag, sin determinar dirección de movimiento.
- Tags **on-metal**, descartables, gestionados desde el WMS (alta/baja de
  etiquetas no es responsabilidad de esta plataforma).
- **Todo en tiempo real**, **se guarda todo** (sin filtrado ni purga automática).
- Soporta **N readers**, configurables desde el panel web (no hardcodeados).

## 1. Componentes

```
rfid_plataforma/
├── sql/
│   └── schema.sql          # Script de creación de la base de datos
├── requirements.txt
└── app/
    ├── app.py                # Servidor principal (Flask + SocketIO)
    ├── diagnostico_sql.py     # Prueba aislada de conexión a SQL Server
    ├── diagnostico_llrp.py    # Prueba aislada de un reader (sin BD ni Flask)
    ├── core/
    │   ├── config.py          # Configuración de conexión a SQL Server
    │   ├── database.py        # Acceso a datos (CRUD readers/antenas, buffer de lecturas)
    │   ├── rfid_manager.py    # Gestión de N conexiones LLRP en paralelo
    │   ├── epc_decoder.py     # Decodificación de EPC (hex / ASCII)
    │   └── timestamp_utils.py
    ├── static/                # CSS y JS del panel web
    └── templates/             # HTML del panel web
```

## 2. Instalación de SQL Server

Si todavía no tenés SQL Server instalado, la opción más simple para
arrancar es **SQL Server Express** (gratuito):

1. Descargar desde
   https://www.microsoft.com/es-ar/sql-server/sql-server-downloads
   (elegir "Express").
2. Durante la instalación, elegir modo "Basic". Anotar el nombre de la
   instancia (por default suele ser `SQLEXPRESS`).
3. Instalar también **SQL Server Management Studio (SSMS)** para poder
   ejecutar el script `schema.sql` con una interfaz gráfica:
   https://learn.microsoft.com/sql/ssms/download-sql-server-management-studio-ssms

## 3. Crear la base de datos

1. Abrir SSMS y conectarse al servidor (`localhost\SQLEXPRESS` si usaste
   el nombre default de instancia).
2. Crear una base de datos vacía llamada `RFID_FPT`:
   ```sql
   CREATE DATABASE RFID_FPT;
   ```
3. Abrir `sql/schema.sql` en SSMS, seleccionar `RFID_FPT` como base de
   datos activa, y ejecutar todo el script (F5). Esto crea las tablas
   `Readers`, `Antenas`, `LecturasRFID`, `LogEstadoReaders`, y las vistas
   `vw_Lecturas`, `vw_ResumenDiarioPorAntena`, `vw_UltimaLecturaPorTag`.

## 4. Instalar el driver ODBC de SQL Server (Windows)

La aplicación Python se conecta a SQL Server vía ODBC. Si no está
instalado, descargar "ODBC Driver 17 (o 18) for SQL Server" desde:

https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server

Después de instalarlo, correr `python diagnostico_sql.py` (paso 7) lista
los drivers detectados para confirmar el nombre exacto a usar en
`config.py` (puede ser `"ODBC Driver 17 for SQL Server"` o `"ODBC Driver
18 for SQL Server"` según cuál se haya instalado).

## 5. Instalación de la aplicación Python

```bash
cd rfid_plataforma
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## 6. Configuración

Editar `app/core/config.py`:

```python
DB_DRIVER = "ODBC Driver 17 for SQL Server"   # el que confirmaste en el paso 4
DB_SERVER = "localhost\\SQLEXPRESS"            # o el nombre real de tu instancia
DB_DATABASE = "RFID_FPT"
DB_TRUSTED_CONNECTION = True                   # usa la sesión de Windows actual
```

Si en cambio usás autenticación SQL Server (usuario/contraseña), poner
`DB_TRUSTED_CONNECTION = False` y completar `DB_USERNAME` / `DB_PASSWORD`.

**No hace falta editar nada sobre readers o antenas en este archivo** —
esos se configuran desde el panel web (ver paso 8). Es la diferencia
clave respecto a la versión anterior de la app.

## 7. Verificar la conexión a la base de datos

Antes de levantar la app completa, conviene confirmar que la conexión a
SQL Server funciona:

```bash
cd app
python diagnostico_sql.py
```

Si todo está bien, debería mostrar la versión del servidor y la lista de
readers configurados (vacía la primera vez).

## 8. Ejecutar la plataforma

```bash
cd app
python app.py
```

Abrir el navegador en `http://localhost:5000`. Ahí vas a ver el panel en
vivo (vacío al principio) y un link a **Configuración**.

### Agregar el primer reader

1. Ir a `http://localhost:5000/configuracion`.
2. Click en "+ Nuevo reader". Completar:
   - Nombre: texto libre, ej. "Reader Expedición FPT"
   - Dirección IP: la IP real del reader en la red de planta
   - Puerto: 5084 (no cambiar salvo caso especial)
   - Modelo / Ubicación: texto libre, informativo
3. Guardar. La aplicación intenta conectarse automáticamente en
   segundos (no hace falta reiniciar nada).
4. Click en "+ Antena" sobre la tarjeta del reader recién creado, y
   agregar cada antena física conectada, indicando el **puerto físico**
   en el reader (1, 2, 3, 4...) donde está conectada.

Repetir para cada reader adicional. La plataforma soporta agregar tantos
como se necesiten, cada uno corriendo en su propia conexión en paralelo.

### Ver lecturas en vivo

Volver a `http://localhost:5000`. Cada reader configurado aparece como
una tarjeta con su estado de conexión (punto verde = conectado). Las
lecturas aparecen en la tabla inferior en tiempo real, con el reader y
antena de origen.

## 9. Explotación de datos (Power BI / SQL directo)

El cliente puede conectarse directamente a la base `RFID_FPT` desde
Power BI (conector "SQL Server") o cualquier herramienta de BI, usando
las vistas ya preparadas:

- **`dbo.vw_Lecturas`**: una fila por lectura, con nombre de antena,
  reader y ubicación ya resueltos (sin necesidad de hacer JOINs).
- **`dbo.vw_ResumenDiarioPorAntena`**: lecturas y tags únicos agrupados
  por día y antena, ideal para gráficos de tendencia.
- **`dbo.vw_UltimaLecturaPorTag`**: última vez que se vio cada tag.

También pueden consultar directamente la tabla `dbo.LecturasRFID` si
necesitan máximo control sobre la consulta.

## 10. Troubleshooting

**`diagnostico_sql.py` falla con "Data source name not found"**
El driver ODBC indicado en `config.py` no coincide con ninguno instalado.
Revisar la lista que imprime el mismo script ("Drivers ODBC instalados")
y copiar el nombre exacto.

**Conecta a SQL Server pero `obtener_readers_activos()` falla**
Probablemente no se ejecutó `sql/schema.sql` contra la base de datos, o
se ejecutó contra una base distinta a la indicada en `DB_DATABASE`.

**Un reader no se conecta (estado queda en rojo)**
Usar `python diagnostico_llrp.py` (editando la IP al inicio del archivo)
para aislar si el problema es de red/reader o de la aplicación.

**Las lecturas no llegan al panel ni a la base de datos, aunque el
reader está "conectado"**
Causa más común: el reader no está reportando tags porque el trigger de
reporte LLRP nunca se cumple. Esta plataforma ya fuerza
`report_every_n_tags = 1` internamente (ver `core/rfid_manager.py`), que
soluciona este problema — no debería reaparecer, pero si se modifica esa
configuración, tenerlo en cuenta.

**Quiero cambiar cada cuánto se guardan las lecturas en SQL Server**
Editar `INTERVALO_FLUSH_SEGUNDOS` en `core/config.py` (default: 2
segundos). Bajarlo da más "tiempo real" en la base, subirlo reduce la
carga de escritura si hay muchos readers reportando en simultáneo.

**¿Qué pasa si SQL Server se cae un momento?**
Las lecturas se siguen acumulando en memoria (hasta
`TAMANO_MAXIMO_BUFFER`, default 50.000) y se reintenta guardar en el
siguiente ciclo de flush. Si la caída es muy prolongada y se supera ese
límite, se empiezan a descartar las lecturas más viejas del buffer (se
loguea un warning cuando esto pasa).
