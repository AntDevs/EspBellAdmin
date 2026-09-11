#!/bin/bash

cd /media/topasta/Dev/git/EspBellAdmin/Proj/source
find . -name "*.py" -exec /media/topasta/Dev/ESP32/firmware/cust_gen/esp_micropython/micropython/mpy-cross/build/mpy-cross -O2 {} \;
rsync -aR --remove-source-files --include="*/" --include="*.mpy" --exclude="*" ././ ../build/
rsync -aR --include="*/" --include="*.html" --include="*.css" --include="*.js" --include="*.json" --exclude="*" ././ ../build/
