# boot.py
import machine

# Мгновенная фиксация питания БЕЗ промежуточного импульса "0" (value=1)
# и БЕЗ вызовов print(), блокирующих USB CDC при работе от БП
try:
    p = machine.Pin(4, machine.Pin.OUT, value=1)
except Exception:
    pass