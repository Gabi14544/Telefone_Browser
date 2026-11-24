# Telefone Browser

Aplicación de escritorio para conectar un Samsung con Android a una PC con Linux Mint. Permite ver y controlar el teléfono en tiempo real y descargar fotos, videos y otros archivos de su almacenamiento compartido. La conexión es local.

La aplicación está pensada para Linux Mint 22.3 de 64 bits con Cinnamon y X11. Usa Python y GTK 3 para el panel, scrcpy para replicar la pantalla y ADB para vincular el teléfono y transferir archivos.

## Instalar en Linux Mint

Podés descargar el proyecto desde GitHub con **Code → Download ZIP** o usar el paquete de instalación. Extraé el archivo y abrí una terminal en la carpeta que contiene `instalar.sh`. Ejecutá lo siguiente con tu usuario habitual.

```bash
bash instalar.sh
```

El instalador agrega las dependencias del sistema si hacen falta, descarga scrcpy y ADB de la publicación oficial de Genymobile y comprueba el SHA-256 antes de instalarlos. Instala la aplicación para tu usuario y agrega **Telefone Browser** al menú de Cinnamon. Podés volver a ejecutar el instalador para actualizarla.

## Conectar tu Samsung por Wi-Fi

Necesitás Android 11 o posterior y una red local que permita que la PC y el teléfono se comuniquen.

1. En el Samsung, abrí **Ajustes → Acerca del teléfono → Información de software**. Tocá **Número de compilación** siete veces y confirmá el PIN si te lo pide.
2. Volvé a Ajustes, entrá en **Opciones de desarrollador** y activá **Depuración inalámbrica**. Aceptá la red si Android lo solicita.
3. En la PC, abrí **Telefone Browser → Conectar por Wi-Fi**. En el Samsung, tocá **Vincular dispositivo mediante código de vinculación**. Ingresá la IP con puerto y el código de seis dígitos que muestra esa ventana. Pulsá **Vincular** mientras el código siga abierto.
4. En la pantalla principal de **Depuración inalámbrica** del Samsung, buscá **Dirección IP y puerto**. Copiá ese valor en **Conectar el teléfono** en la PC. Los dos puertos suelen ser distintos.
5. Seleccioná el Samsung y pulsá **Iniciar transmisión** o **Explorar archivos**.

En conexiones siguientes podés usar directamente el paso 4 con la dirección que muestre el teléfono. Si una red de invitados aísla los dispositivos, usá una red local que permita la comunicación o conectá por USB. Podés desactivar **Depuración inalámbrica** en el Samsung al terminar.

### Conectar por USB

Activá **Depuración USB** en Opciones de desarrollador, usá un cable de datos, desbloqueá el teléfono y aceptá la autorización de la PC. Pulsá **Actualizar** en la app. Si aparece **Sin permiso USB**, instalá las reglas de Ubuntu y volvé a conectar el teléfono.

```bash
sudo apt install android-sdk-platform-tools-common
```

Si Linux indica que tu usuario no está en el grupo `plugdev`, agregalo con `sudo usermod -aG plugdev "$USER"` y volvé a iniciar sesión.

## Pantalla y archivos

- **Fluido** arranca con un máximo de 720 px en el lado largo, hasta 24 FPS y 2 Mb/s. Para el Celeron N2808 con 4 GB de RAM, probá **Ahorro** (540 px, 15 FPS, 1 Mb/s) si hay tirones. **Detalle** sube a 1080 px y 30 FPS. El rendimiento depende del teléfono, la red y la carga de la PC.
- Arrastrá la barra de título para mover la ventana y los bordes para cambiar su tamaño. El panel tiene **Mostrar**, **Ocultar**, **Pantalla completa** y **Siempre visible**. Ocultar minimiza la ventana y mantiene la transmisión activa. Volvé al panel con `Alt+Tab`.
- Usá el mouse y el teclado sobre la pantalla transmitida. Si solo querés ver, desactivá **Control con mouse y teclado** antes de iniciar. La transmisión usa video H.264 y tiene el audio desactivado.
- En **Explorar archivos**, abrí una carpeta o usá los accesos a Cámara, Imágenes y Descargas. Seleccioná uno o más archivos y elegí una carpeta de la PC. La app conserva los originales del teléfono y, si un nombre ya existe en la PC, guarda la nueva copia con un número.
- Android restringe el acceso a datos privados de aplicaciones. Algunas aplicaciones o pantallas protegidas pueden aparecer en negro por las restricciones de captura de Android.

## Desarrollar o probar

Usá la copia del repositorio que ya esté abierta. En Linux X11 con GTK 3, `adb`, `scrcpy` 3.3.4, `wmctrl` y `xdotool` en el PATH, ejecutá `./abrir` desde la raíz. También podés probar la instalación para tu usuario y abrir la aplicación desde Cinnamon.

Una prueba completa con dispositivo requiere un Android autorizado. Vinculalo por Wi-Fi, iniciá el video, escribí o tocá algo en la ventana, ocultala y recuperala. Descargá una foto y abrila en la PC para comprobar la transferencia.

## Posibles ampliaciones

Capturas de pantalla desde el panel, grabación local, atajos configurables, audio opcional en dispositivos compatibles y envío de archivos desde la PC al teléfono desde el explorador.

[Proyecto scrcpy y documentación de Genymobile](https://github.com/Genymobile/scrcpy/tree/v3.3.4)
