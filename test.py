#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import json
import sys

def full_diagnostic():
    XUI_PANEL_HOST = "http://185.114.73.28:9421"
    XUI_USERNAME = "T0IoWo99kh"
    XUI_PASSWORD = "MDNoJDxu3D"
    
    print("🔍 ПОЛНАЯ ДИАГНОСТИКА ПОДКЛЮЧЕНИЯ 3X-UI")
    print("=" * 50)
    
    # 1. Проверка сети
    print("1. 🖧 Проверка сетевого подключения...")
    try:
        response = requests.get(XUI_PANEL_HOST, timeout=10)
        print(f"   ✅ Сеть: Хост доступен (статус {response.status_code})")
    except requests.exceptions.ConnectTimeout:
        print("   ❌ Сеть: Таймаут подключения")
        return
    except requests.exceptions.ConnectionError:
        print("   ❌ Сеть: Ошибка соединения - проверьте URL и доступность сервера")
        return
    except Exception as e:
        print(f"   ❌ Сеть: Неизвестная ошибка - {e}")
        return
    
    # 2. Проверка доступности панели
    print("2. 🌐 Проверка панели...")
    try:
        response = requests.get(XUI_PANEL_HOST, timeout=10)
        if "3x-ui" in response.text or "x-ui" in response.text:
            print("   ✅ Панель: Обнаружена 3x-ui/x-ui панель")
        else:
            print("   ⚠️  Панель: Доступна, но не похожа на 3x-ui")
    except Exception as e:
        print(f"   ❌ Панель: Ошибка - {e}")
    
    # 3. Проверка авторизации
    print("3. 🔐 Проверка авторизации...")
    session = requests.Session()
    login_url = f"{XUI_PANEL_HOST}/login"
    
    try:
        response = session.post(login_url, data={
            'username': XUI_USERNAME,
            'password': XUI_PASSWORD
        }, timeout=10)
        
        print(f"   📊 Статус: {response.status_code}")
        print(f"   📝 Ответ: {response.text[:100]}...")
        
        if response.status_code == 200:
            # Проверяем различные признаки успеха
            if "success" in response.text.lower():
                print("   ✅ Авторизация: Успешна (обнаружен 'success')")
            elif "true" in response.text.lower():
                print("   ✅ Авторизация: Успешна (обнаружен 'true')")
            else:
                print("   ⚠️  Авторизация: Статус 200, но неясный ответ")
        else:
            print("   ❌ Авторизация: Неуспешна")
            
    except Exception as e:
        print(f"   ❌ Авторизация: Ошибка - {e}")
    
    print("=" * 50)
    print("💡 РЕКОМЕНДАЦИИ:")
    print("1. Проверьте URL панели в браузере")
    print("2. Убедитесь, что логин/пароль верные")
    print("3. Проверьте, что панель запущена и доступна")
    print("4. Возможно, изменился API endpoint")

if __name__ == "__main__":
    full_diagnostic()