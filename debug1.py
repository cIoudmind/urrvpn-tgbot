#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import json
import sys
import traceback
from urllib.parse import urlparse

def debug_panel_connection():
    XUI_PANEL_HOST = "http://185.114.73.28:9421"
    XUI_USERNAME = "T0IoWo99kh"
    XUI_PASSWORD = "MDNoJDxu3D"
    
    print("🐛 ДЕБАГ ПОДКЛЮЧЕНИЯ К 3X-UI ПАНЕЛИ")
    print("=" * 60)
    
    # 1. Проверка базовой доступности
    print("1. 🔍 Проверка доступности хоста...")
    try:
        response = requests.get(XUI_PANEL_HOST, timeout=10, verify=False)
        print(f"   ✅ Хост отвечает, статус: {response.status_code}")
        print(f"   📄 Заголовки: {dict(response.headers)}")
    except requests.exceptions.ConnectTimeout:
        print("   ❌ Таймаут подключения - панель не отвечает")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"   ❌ Ошибка соединения: {e}")
        return False
    except Exception as e:
        print(f"   ❌ Неизвестная ошибка: {e}")
        return False
    
    # 2. Проверка структуры панели
    print("\n2. 🌐 Анализ структуры панели...")
    try:
        response = requests.get(XUI_PANEL_HOST, timeout=10, verify=False)
        content_lower = response.text.lower()
        
        if "3x-ui" in content_lower or "x-ui" in content_lower:
            print("   ✅ Обнаружена 3x-ui/x-ui панель")
        elif "login" in content_lower:
            print("   ✅ Обнаружена страница логина")
        else:
            print("   ⚠️  Нестандартная страница")
            
        # Ищем формы логина
        if 'form' in content_lower and ('password' in content_lower or 'username' in content_lower):
            print("   ✅ Обнаружена форма логина")
    except Exception as e:
        print(f"   ❌ Ошибка анализа: {e}")
    
    # 3. Тестирование различных endpoint'ов
    print("\n3. 🔄 Тестирование API endpoint'ов...")
    
    endpoints = [
        "/login",
        "/api/login", 
        "/xui/login",
        "/xui/api/login",
        "/panel/login",
        "/auth/login"
    ]
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
        'Accept': '*/*',
        'Content-Type': 'application/x-www-form-urlencoded'
    })
    
    for endpoint in endpoints:
        full_url = XUI_PANEL_HOST + endpoint
        print(f"   🔗 Тестируем: {endpoint}")
        
        try:
            # Пробуем POST с form data
            resp = session.post(full_url, data={
                'username': XUI_USERNAME,
                'password': XUI_PASSWORD
            }, timeout=10, verify=False)
            
            print(f"      📊 Статус: {resp.status_code}")
            print(f"      📝 Ответ: {resp.text[:100]}...")
            print(f"      🍪 Куки: {len(session.cookies.get_dict())} шт")
            
            if resp.status_code == 200:
                # Проверяем признаки успеха
                success_indicators = [
                    'success' in resp.text.lower(),
                    'true' in resp.text.lower(),
                    'dashboard' in resp.text.lower(), 
                    'welcome' in resp.text.lower(),
                    '"success":true' in resp.text,
                    '"code":0' in resp.text
                ]
                
                if any(success_indicators):
                    print(f"      ✅ ВОЗМОЖНО УСПЕШНАЯ АВТОРИЗАЦИЯ на {endpoint}!")
                    
                    # Пробуем получить инбаунды
                    inbound_test = session.get(XUI_PANEL_HOST + "/xui/inbound/list", timeout=10, verify=False)
                    print(f"      📡 Тест инбаундов: статус {inbound_test.status_code}")
                    
                    if inbound_test.status_code == 200:
                        print("      🎉 АВТОРИЗАЦИЯ УСПЕШНА! Можем работать с API")
                        return True
                        
        except Exception as e:
            print(f"      ❌ Ошибка: {e}")
            continue
    
    # 4. Альтернативные методы авторизации
    print("\n4. 🔐 Альтернативные методы авторизации...")
    
    # Метод с JSON
    print("   📋 Пробуем JSON авторизацию...")
    try:
        session2 = requests.Session()
        session2.headers.update({'Content-Type': 'application/json'})
        
        resp = session2.post(XUI_PANEL_HOST + "/login", 
                           json={'username': XUI_USERNAME, 'password': XUI_PASSWORD},
                           timeout=10, verify=False)
        print(f"      JSON статус: {resp.status_code}")
        print(f"      JSON ответ: {resp.text[:100]}...")
    except Exception as e:
        print(f"      JSON ошибка: {e}")
    
    # 5. Проверка версии панели
    print("\n5. 🔎 Поиск информации о версии панели...")
    try:
        # Частые endpoint'ы для информации
        info_endpoints = ["/xui/", "/api/", "/panel/", "/server/status"]
        
        for endpoint in info_endpoints:
            try:
                resp = requests.get(XUI_PANEL_HOST + endpoint, timeout=5, verify=False)
                if resp.status_code == 200:
                    print(f"   🔗 {endpoint} - доступен")
            except:
                continue
    
    except Exception as e:
        print(f"   ❌ Ошибка поиска версии: {e}")
    
    print("\n" + "=" * 60)
    print("💡 ВОЗМОЖНЫЕ ПРИЧИНЫ И РЕШЕНИЯ:")
    print("1. ❌ Неверный URL панели - проверьте в браузере")
    print("2. ❌ Неверные логин/пароль - проверьте в браузере") 
    print("3. ❌ Изменился API endpoint - проверьте документацию")
    print("4. ❌ Блокировка по IP - проверьте настройки панели")
    print("5. ❌ Требуется HTTPS - попробуйте https://")
    print("6. ❌ Кастомная авторизация - нужна адаптация кода")
    
    return False

if __name__ == "__main__":
    debug_panel_connection()