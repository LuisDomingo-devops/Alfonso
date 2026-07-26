import sqlite3
conn = sqlite3.connect('/home/ubuntu/Alfonso/data/memory.db')
conn.row_factory = sqlite3.Row
for r in conn.execute('SELECT * FROM messages'):
    print(dict(r))
