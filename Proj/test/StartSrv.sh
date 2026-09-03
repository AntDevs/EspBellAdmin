#!/bin/bash

# Запускаем Python-сервер в фоновом режиме
python3 -m http.server 8000 &
SERVER_PID=$!

# Даем серверу секунду на инициализацию
sleep 1

# Открываем страницу в браузере (в Linux используется xdg-open вместо open)
xdg-open "http://localhost:8000/test-auth.html"

# Ожидаем завершения работы сервера, чтобы сессия терминала не закрывалась сразу
wait $SERVER_PID
