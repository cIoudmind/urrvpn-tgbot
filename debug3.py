import socket

def check_network():
    host = "185.114.73.28"
    port = 9421
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((host, port))
        
        if result == 0:
            print(f"✅ Порт {port} на {host} открыт")
        else:
            print(f"❌ Порт {port} на {host} закрыт или недоступен")
            
        sock.close()
    except Exception as e:
        print(f"❌ Ошибка сети: {e}")

check_network()