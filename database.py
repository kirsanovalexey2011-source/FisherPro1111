import sqlite3
import json
from datetime import datetime
import os


class Database:
    def __init__(self, db_path='olympiads.db'):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='events'")
                table_exists = cursor.fetchone()

                if not table_exists:
                    cursor.execute('''
                        CREATE TABLE events (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            title TEXT NOT NULL,
                            dates TEXT NOT NULL,
                            color TEXT DEFAULT '#FF6B6B',
                            registration_dates TEXT DEFAULT '[]'
                        )
                    ''')
                    conn.commit()
                    print("✅ Таблица создана")
                else:
                    # Проверяем структуру
                    cursor.execute("PRAGMA table_info(events)")
                    columns = [col[1] for col in cursor.fetchall()]

                    # Удаляем лишние поля если есть
                    if 'notes' in columns:
                        try:
                            cursor.execute('ALTER TABLE events DROP COLUMN notes')
                            print("✅ Поле notes удалено")
                        except:
                            pass

                    if 'icon_path' in columns:
                        try:
                            cursor.execute('ALTER TABLE events DROP COLUMN icon_path')
                            print("✅ Поле icon_path удалено")
                        except:
                            pass
        except Exception as e:
            print(f"Ошибка init_db: {e}")

    def get_events_by_date(self, date_str):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM events', ())
                results = []

                for row in cursor.fetchall():
                    try:
                        dates = json.loads(row['dates'])
                        if date_str in dates:
                            results.append(row)
                    except:
                        continue

                return results
        except Exception as e:
            print(f"Ошибка get_events_by_date: {e}")
            return []

    def get_events_by_month(self, year, month):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM events', ())

                events_by_date = {}

                for row in cursor.fetchall():
                    try:
                        dates = json.loads(row['dates'])
                        for date in dates:
                            try:
                                date_obj = datetime.strptime(date, '%Y-%m-%d')
                                if date_obj.year == year and date_obj.month == month:
                                    if date not in events_by_date:
                                        events_by_date[date] = []
                                    events_by_date[date].append(row)
                            except:
                                continue
                    except:
                        continue

                return events_by_date
        except Exception as e:
            print(f"Ошибка get_events_by_month: {e}")
            return {}

    def get_all_events(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM events ORDER BY id DESC')
                return cursor.fetchall()
        except Exception as e:
            print(f"Ошибка get_all_events: {e}")
            return []

    def get_statistics(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) as total FROM events')
                total = cursor.fetchone()[0]

                cursor.execute('SELECT dates FROM events')
                all_dates = set()
                for row in cursor.fetchall():
                    try:
                        dates = json.loads(row[0])
                        all_dates.update(dates)
                    except:
                        continue

                return {
                    'total_events': total,
                    'total_dates': len(all_dates)
                }
        except Exception as e:
            print(f"Ошибка get_statistics: {e}")
            return {'total_events': 0, 'total_dates': 0}

    def add_event(self, title, dates, color, registration_dates=None):
        try:
            dates_json = json.dumps(dates)
            reg_json = json.dumps(registration_dates) if registration_dates else json.dumps([])

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'INSERT INTO events (title, dates, color, registration_dates) VALUES (?, ?, ?, ?)',
                    (title, dates_json, color, reg_json)
                )
                conn.commit()
                return cursor.lastrowid
        except Exception as e:
            print(f"Ошибка add_event: {e}")
            return None

    def update_event(self, event_id, title, dates, color, registration_dates=None):
        try:
            dates_json = json.dumps(dates)
            reg_json = json.dumps(registration_dates) if registration_dates else json.dumps([])

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'UPDATE events SET title=?, dates=?, color=?, registration_dates=? WHERE id=?',
                    (title, dates_json, color, reg_json, event_id)
                )
                conn.commit()
        except Exception as e:
            print(f"Ошибка update_event: {e}")

    def delete_event(self, event_id):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM events WHERE id=?', (event_id,))
                conn.commit()
        except Exception as e:
            print(f"Ошибка delete_event: {e}")