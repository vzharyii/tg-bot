import sys
import os
import time
import subprocess

# Настройки
TARGET_SCRIPT = "main.py"  # Файл, который запускаем
WATCH_EXTENSIONS = {".py", ".env", ".pem"}  # Расширения для отслеживания
IGNORE_DIRS = {"__pycache__", ".git", ".idea", "venv", "env"}
POLL_INTERVAL = 1.0  # Сек

def get_file_mtimes(root_dir):
    """Сканирует директорию и возвращает словарь {путь: время_изменения}"""
    mtimes = {}
    for root, dirs, files in os.walk(root_dir):
        # Исключаем ненужные папки
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")]
        
        for f in files:
            _, ext = os.path.splitext(f)
            if ext in WATCH_EXTENSIONS:
                path = os.path.join(root, f)
                try:
                    mtimes[path] = os.stat(path).st_mtime
                except OSError:
                    pass
    return mtimes

def main():
    print(f"🚀 Запускаем авто-рестарт для: {TARGET_SCRIPT}")
    print(f"👀 Следим за файлами: {', '.join(WATCH_EXTENSIONS)}")
    
    # Запускаем процесс
    cmd = [sys.executable, TARGET_SCRIPT]
    process = subprocess.Popen(cmd)
    
    last_mtimes = get_file_mtimes(".")
    
    try:
        while True:
            time.sleep(POLL_INTERVAL)
            current_mtimes = get_file_mtimes(".")
            
            changed_files = []
            
            # 1. Проверяем удаленные или новые файлы (изменился список ключей)
            if current_mtimes.keys() != last_mtimes.keys():
                changed_files.append("Список файлов изменился")
            else:
                # 2. Проверяем изменения содержимого
                for path, mtime in current_mtimes.items():
                    if last_mtimes.get(path) != mtime:
                        changed_files.append(path)
                        break
            
            if changed_files:
                print(f"\n♻️ Обнаружены изменения ({changed_files[0]}...). Перезапуск!")
                
                # Убиваем старый процесс
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    print("⚠️ Не хотел закрываться, убиваем принудительно...")
                    process.kill()
                    process.wait()

                print("---------------------------------------------------")
                # Запускаем новый
                process = subprocess.Popen(cmd)
                last_mtimes = current_mtimes
                
    except KeyboardInterrupt:
        print("\n🛑 Останавливаем бот...")
        process.terminate()
        process.wait()
        print("✅ Готово.")

if __name__ == "__main__":
    main()
