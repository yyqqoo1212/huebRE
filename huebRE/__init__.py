import pymysql

# 让 PyMySQL 兼容 Django 的 MySQL 驱动
pymysql.install_as_MySQLdb()
