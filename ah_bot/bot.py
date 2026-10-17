import cv2
import mss
import numpy as np
import os
import time
import pydirectinput
import win32gui
import win32api
import re
import win32con
import random
import pytesseract

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

class RedstoneDetector:
    def __init__(self):
        self.debug_mode = True
        if self.debug_mode:
            os.makedirs("debug", exist_ok=True)
            print("📂 Режим отладки ВКЛЮЧЕН. Фото сохраняются в 'debug'")

        self.MIN_PRICE = 10000
        self.BUY_LIMIT = 35000
        self.SELL_PRICE = 50000
        self.REFRESH_INTERVAL = 5

        self.window_handle = None
        self.monitor = None
        self.find_minecraft_window()
        self.sct = mss.MSS()

        self.confidence_threshold = 0.81
        self.templates = {}
        self.load_templates()

        pydirectinput.FAILSAFE = False
        self.auto_buy = False
        self.bought_items = []
        self.sell_in_progress = False
        self.last_refresh_time = 0
        self.started = False
        self.is_busy = False

    # БАЗОВЫЕ МЕТОДЫ
    def find_minecraft_window(self):
        print("🔍 Ищу окно Minecraft...")
        window_titles = ["Minecraft", "Minecraft 1.", "Minecraft*", "Minecraft Launcher"]
        def enum_callback(hwnd, windows):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                for t in window_titles:
                    if t in title:
                        windows.append((hwnd, title))
                        break
            return True
        windows = []
        win32gui.EnumWindows(enum_callback, windows)
        if not windows:
            self.monitor = {"left": 0, "top": 0, "width": 1920, "height": 1080}
            return
        self.window_handle, title = windows[0]
        win32gui.ShowWindow(self.window_handle, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(self.window_handle)
        time.sleep(0.5)
        rect = win32gui.GetWindowRect(self.window_handle)
        self.monitor = {"left": rect[0], "top": rect[1], "width": rect[2]-rect[0], "height": rect[3]-rect[1]}

    def load_templates(self, folder="templates/"):
        if not os.path.exists(folder):
            os.makedirs(folder)
            return
        for f in os.listdir(folder):
            if f.endswith(('.png', '.jpg', '.jpeg')):
                path = os.path.join(folder, f)
                img = cv2.imread(path, cv2.IMREAD_COLOR)
                if img is not None:
                    name = os.path.splitext(f)[0]
                    self.templates[name] = img

    def capture_frame(self):
        shot = self.sct.grab(self.monitor)
        frame = np.array(shot)
        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        return frame

    def find_template_on_frame(self, frame, name, threshold=None):
        if threshold is None: threshold = self.confidence_threshold
        if name not in self.templates: return None
        template = self.templates[name]
        best = None; best_conf = 0
        for scale in np.arange(0.5, 1.6, 0.05):
            w = int(template.shape[1] * scale); h = int(template.shape[0] * scale)
            if w < 5 or h < 5: continue
            scaled = cv2.resize(template, (w, h), interpolation=cv2.INTER_CUBIC)
            result = cv2.matchTemplate(frame, scaled, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val > best_conf:
                best_conf = max_val; x, y = max_loc
                best = {'x': x, 'y': y, 'w': w, 'h': h, 'center_x': x + w//2, 'center_y': y + h//2, 'confidence': max_val}
        if best and best_conf >= threshold:
            return best
        return None

    def wait_for_template(self, name, timeout=3.0):
        start = time.time()
        while time.time() - start < timeout:
            frame = self.capture_frame()
            pos = self.find_template_on_frame(frame, name)
            if pos: return pos
            time.sleep(0.3)
        return None

    def move_mouse_away(self):
        if self.window_handle is None: return
        rect = win32gui.GetWindowRect(self.window_handle)
        x = rect[0] + random.randint(20, 100)
        y = rect[3] - random.randint(20, 80)
        pydirectinput.moveTo(x, y, duration=0.15)
        time.sleep(0.05)

    def click_abs(self, x, y):
        if self.window_handle:
            win32gui.SetForegroundWindow(self.window_handle)
            time.sleep(0.05)
        pydirectinput.moveTo(x, y, duration=0.15)
        time.sleep(0.05)
        pydirectinput.click()
        time.sleep(0.2)

    def click_template(self, pos):
        if pos is None: return False
        x = self.monitor["left"] + pos['center_x']; y = self.monitor["top"] + pos['center_y']
        self.click_abs(x, y)
        return True

    def move_to_item(self, item):
        x = self.monitor["left"] + item['center_x']; y = self.monitor["top"] + item['center_y']
        pydirectinput.moveTo(x, y, duration=0.15)
        time.sleep(0.15)

    def single_click_item(self, item):
        x = self.monitor["left"] + item['center_x']; y = self.monitor["top"] + item['center_y']
        print(f"🖱️ Одинарный клик на {item['name']} в ({x}, {y})")
        if self.window_handle:
            win32gui.SetForegroundWindow(self.window_handle)
            time.sleep(0.05)
        self.move_mouse_away()
        time.sleep(0.05)
        pydirectinput.moveTo(x, y, duration=0.15)
        time.sleep(0.1)
        pydirectinput.click()
        time.sleep(0.6)  # Вернули как было

    def open_auction(self):
        if self.window_handle:
            win32gui.SetForegroundWindow(self.window_handle)
            time.sleep(0.2)
        pydirectinput.write('/ah')
        time.sleep(0.1)
        pydirectinput.press('enter')
        time.sleep(1.0)
        self.move_mouse_away()

    def navigate_to_auction(self):
        print("\n🧭 НАВИГАЦИЯ...")
        self.open_auction()
        chest = self.wait_for_template('start_chest', timeout=5.0)
        if not chest: return False
        self.click_template(chest)
        time.sleep(1.0)
        netherite = self.wait_for_template('start_netherite', timeout=4.0)
        if not netherite: return False
        self.click_template(netherite)
        time.sleep(1.0)
        self.refresh_auction()
        self.move_mouse_away()
        return True

    def refresh_auction(self):
        refresh = self.wait_for_template('refresh_star', timeout=3.0)
        if refresh:
            self.click_template(refresh)
            time.sleep(0.5)
            self.last_refresh_time = time.time()
            self.move_mouse_away()
            return True
        return False

    # ==========================================
    # ЧТЕНИЕ ЦЕНЫ (простая версия + исключение 99999)
    # ==========================================
    def read_price(self, frame, x, y, w, h):
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (40, 100, 100), (90, 255, 255))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2,2), np.uint8))

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        item_center_x = x + w // 2
        item_center_y = y + h // 2

        lines = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 30:
                continue
            bx, by, bw, bh = cv2.boundingRect(cnt)
            center_x = bx + bw // 2
            center_y = by + bh // 2

            if center_x < item_center_x + 50 or bh > 40 or bw > 150:
                continue
            lines.append((bx, by, bw, bh))

        if not lines:
            return None

        lines.sort(key=lambda b: b[1])

        for (lx, ly, lw, lh) in lines:
            pad_x = 150
            pad_y = 5
            roi_x = max(0, lx - pad_x)
            roi_y = max(0, ly - pad_y)
            roi_w = min(lw + pad_x * 2, frame.shape[1] - roi_x)
            roi_h = min(lh + pad_y * 2, frame.shape[0] - roi_y)

            roi = frame[roi_y:roi_y + roi_h, roi_x:roi_x + roi_w]
            roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

            _, thresh = cv2.threshold(roi_gray, 120, 255, cv2.THRESH_BINARY_INV)

            if self.debug_mode:
                cv2.imwrite("debug/5_line_crop.png", roi)
                cv2.imwrite("debug/6_line_thresh.png", thresh)

            enlarged = cv2.resize(thresh, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
            config = '--psm 7 -c tessedit_char_whitelist=0123456789$.,'
            raw_text = pytesseract.image_to_string(enlarged, config=config)

            numbers = re.findall(r'\$\s?\d[\d,]*|\d[\d,]*', raw_text)

            if self.debug_mode:
                print(f"   [Строка] '{raw_text.strip()}' -> {numbers}")

            for num in numbers:
                clean = num.replace('$', '').replace(',', '')
                if len(clean) == 5 or len(clean) == 6:
                    price = int(clean)
                    # ИСКЛЮЧЕНИЕ: не покупаем 99999 (это обрезка от 9,999,999)
                    if price == 99999:
                        continue
                    if self.MIN_PRICE <= price <= self.BUY_LIMIT:
                        return price

        return None

    # ==========================================
    # НОВЫЙ ПОИСК КНОПКИ (склеивает 9 квадратов в одну)
    # ==========================================
    def find_buy_button(self, frame):
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        green_mask = cv2.inRange(hsv, (40, 100, 100), (90, 255, 255))
        kernel = np.ones((15, 15), np.uint8)
        green_mask = cv2.dilate(green_mask, kernel, iterations=2)
        contours, _ = cv2.findContours(green_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None; best_area = 0
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area > 300 and area > best_area:
                best_area = area; best = cnt
        if best is not None:
            x, y, w, h = cv2.boundingRect(best)
            return {'center_x': x + w // 2, 'center_y': y + h // 2}
        return None

    # ==========================================
    # ПОИСК ПРЕДМЕТОВ И МГНОВЕННАЯ ПОКУПКА
    # ==========================================
    def find_items(self, frame):
        found = []
        nav_buttons = ['start_chest', 'start_netherite', 'refresh_star']
        for name, template in self.templates.items():
            if name in nav_buttons: continue
            for scale in np.arange(0.5, 1.6, 0.05):
                w = int(template.shape[1] * scale); h = int(template.shape[0] * scale)
                if w < 5 or h < 5: continue
                scaled = cv2.resize(template, (w, h), interpolation=cv2.INTER_CUBIC)
                result = cv2.matchTemplate(frame, scaled, cv2.TM_CCOEFF_NORMED)
                locations = np.where(result >= self.confidence_threshold)
                for x, y in zip(locations[1], locations[0]):
                    conf = result[y, x]
                    if self.is_duplicate(found, x, y): continue
                    item = {'name': name, 'x': x, 'y': y, 'w': w, 'h': h,
                            'center_x': x + w//2, 'center_y': y + h//2,
                            'confidence': conf, 'price': None, 'is_profitable': False}
                    self.move_to_item(item)
                    time.sleep(0.5)
                    fresh_frame = self.capture_frame()
                    price = self.read_price(fresh_frame, x, y, w, h)
                    item['price'] = price
                    item['is_profitable'] = (price is not None and price <= self.BUY_LIMIT)
                    if item['is_profitable']:
                        self.buy_item(item)
                        return True
                    found.append(item)
                    self.move_mouse_away()
                    price_str = str(price) if price else "???"
                    status = "✅ ВЫГОДНО!" if item['is_profitable'] else (f"💰 {price}" if price else "❌ ???")
                    print(f"   {name}: {price_str} - {status}")
        return found

    def is_duplicate(self, items, x, y, threshold=20):
        for it in items:
            if abs(it['x'] - x) < threshold and abs(it['y'] - y) < threshold:
                return True
        return False

    # ==========================================
    # ПОКУПКА И ПРОДАЖА
    # ==========================================
    def buy_item(self, item):
        if self.is_busy: return
        self.is_busy = True
        try:
            if item['price'] is None or item['price'] > self.BUY_LIMIT or item['price'] < self.MIN_PRICE:
                print("⚠️ Цена вне лимитов, пропускаю")
                return
            key = f"{item['x']}_{item['y']}"
            if key in self.bought_items: return
            
            print(f"🛒 ПОКУПАЮ {item['name']} за {item['price']}")
            self.single_click_item(item)
            buy_button = self.find_buy_button(self.capture_frame())
            if buy_button:
                self.click_abs(self.monitor["left"] + buy_button['center_x'], self.monitor["top"] + buy_button['center_y'])
                time.sleep(0.5)
                self.bought_items.append(key)
                print(f"✅ {item['name']} куплен!")
            else:
                print(f"   ❌ Кнопка не найдена")
            
            self.sell_redstone()
        finally:
            self.is_busy = False

    def sell_redstone(self):
        if self.sell_in_progress: return
        self.sell_in_progress = True
        print("\n💰 ПРОДАЖА...")
        try:
            if self.window_handle:
                win32gui.SetForegroundWindow(self.window_handle)
                time.sleep(0.3)
            self.move_mouse_away()
            time.sleep(0.1)
            pydirectinput.press('esc')
            time.sleep(0.4)
            pydirectinput.press('1')
            time.sleep(0.3)
            pydirectinput.write(f'/ah sell {self.SELL_PRICE}')
            time.sleep(0.15)
            pydirectinput.press('enter')
            time.sleep(0.6)
            pydirectinput.write('/ah')
            time.sleep(0.15)
            pydirectinput.press('enter')
            time.sleep(0.6)
            self.move_mouse_away()
            print("   ✅ Продажа завершена")
        except Exception as e:
            print(f"   ❌ Ошибка продажи: {e}")
        self.sell_in_progress = False

    # ==========================================
    # ОТРИСОВКА
    # ==========================================
    def draw_boxes(self, frame, items):
        out = frame.copy()
        for item in items:
            x, y, w, h = item['x'], item['y'], item['w'], item['h']
            is_profitable = item.get('is_profitable', False)
            price = item.get('price')
            color = (0, 255, 0) if is_profitable else ((0, 255, 255) if price else (0, 0, 255))
            thick = 3 if is_profitable else 1
            cv2.rectangle(out, (x, y), (x + w, y + h), color, thick)
            label = f"{item['name']}: {price if price else '???'}"
            if is_profitable: label += " ✅"
            cv2.putText(out, label, (x, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
        return out

    # ==========================================
    # ГЛАВНЫЙ ЦИКЛ
    # ==========================================
    def run(self):
        print("=" * 60)
        print("🔍 БОТ ДЛЯ ПЕРЕПРОДАЖИ РЕДСТОУНА (Tesseract + исключение 99999)")
        print(f"💰 Лимит покупки: ${self.BUY_LIMIT:,}")
        print(f"💰 Цена продажи: ${self.SELL_PRICE:,}")
        print("=" * 60)
        required = ['start_chest', 'start_netherite', 'refresh_star']
        missing = [t for t in required if t not in self.templates]
        if missing:
            print(f"❌ Отсутствуют шаблоны: {missing}")
            return
        print("⏳ Ожидание нажатия 's'...")
        while not self.started:
            frame = self.capture_frame()
            if frame is not None:
                debug = frame.copy()
                cv2.putText(debug, "Press 's' to START", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                cv2.imshow("Auction Bot - Waiting", debug)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('s'):
                self.started = True
                break
            elif key == ord('q'):
                cv2.destroyAllWindows()
                return
        if not self.navigate_to_auction():
            print("⚠️ Не удалось выполнить начальную навигацию.")
        self.last_refresh_time = time.time()
        while True:
            now = time.time()
            if now - self.last_refresh_time >= self.REFRESH_INTERVAL:
                self.refresh_auction()
                self.last_refresh_time = now
            print("\n🔄 НОВЫЙ ЦИКЛ")
            frame = self.capture_frame()
            if frame.shape[0] < 10 or frame.shape[1] < 10:
                time.sleep(0.5)
                continue

            result = self.find_items(frame)
            if result is True:
                time.sleep(0.5)
                self.navigate_to_auction()
                self.last_refresh_time = time.time()
                continue
            else:
                items = result
                print("   🔄 Нет выгодных предметов, обновляю...")
                self.refresh_auction()
                self.last_refresh_time = time.time()

            debug = self.draw_boxes(frame, items)
            cv2.imshow("Auction Bot", debug)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('n'):
                self.navigate_to_auction()
            elif key == ord('r'):
                self.refresh_auction()
            elif key == ord('t'):
                cv2.imwrite(f"auction_{int(time.time())}.png", debug)
            time.sleep(0.3)
        cv2.destroyAllWindows()
        print("🛑 Бот остановлен")

if __name__ == "__main__":
    detector = RedstoneDetector()
    detector.run()