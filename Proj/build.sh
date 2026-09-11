#!/bin/bash

cd /media/topasta/Dev/git/EspBellAdmin/Proj/source
find . -name "*.py" -exec /media/topasta/Dev/ESP32/firmware/cust_gen/esp_micropython/micropython/mpy-cross/build/mpy-cross -O2 {} \;
rm -rf ../build
rsync -aR --remove-source-files --include="*/" --include="*.mpy" --exclude="*" ././ ../build/
rsync -aR --exclude="*.py" ././ ../build/


# rync -aR --remove-source-files --include="*/" --include="*.mpy" --exclude="*" ././ ../build/
# rsync -aR --include="*/" --include="*.{html,css,js,json}" --exclude="*" ././ ../build/
# rsync -aR --exclude="*.py" --include="*/" --include="*"  ././ ../build/
