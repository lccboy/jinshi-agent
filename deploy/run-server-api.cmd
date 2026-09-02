@echo off
cd /d C:\nginx\html\DSH
for /f %%i in ('C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe -c "import certifi; print(certifi.where())"') do set SSL_CERT_FILE=%%i
C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe services\market_data_service.py --host 127.0.0.1 --port 8787 --data data >> data\runs\api.stdout.log 2>> data\runs\api.stderr.log
