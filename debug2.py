import requests

def simple_login_test():
    panel = "http://185.114.73.28:9421"
    username = "T0IoWo99kh"
    password = "MDNoJDxu3D"
    
    session = requests.Session()
    
    # Пробуем самые популярные endpoint'ы
    endpoints = [
        "/login",
        "/xui/login", 
        "/api/login"
    ]
    
    for endpoint in endpoints:
        print(f"Пробуем {endpoint}...")
        try:
            resp = session.post(panel + endpoint, data={
                'username': username,
                'password': password
            }, timeout=10)
            
            print(f"Статус: {resp.status_code}")
            print(f"Текст: {resp.text[:200]}")
            print("="*50)
            
        except Exception as e:
            print(f"Ошибка: {e}")
            print("="*50)

simple_login_test()