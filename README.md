# PyQt6 文件服务器

一个简单的桌面文件服务器工具，可以选择要开放的文件夹，启动后在局域网内通过浏览器访问文件。

## 运行

```powershell
python app.py
```

如果缺少 PyQt6：

```powershell
python -m pip install -r requirements.txt
```

## 使用

1. 点击“选择文件夹”。
2. 设置端口，默认是 `8000`。
3. 点击“启动”。
4. 使用界面中显示的地址访问文件。
5. 在浏览器目录页面里，点击文件夹右侧的“下载文件夹”可以下载 zip。
6. 点击窗口关闭按钮会最小化到托盘；右键托盘图标可以退出。

## 打包 exe

```powershell
python -m PyInstaller --noconfirm --clean --windowed --onefile --name "文件服务器" app.py
```

也可以直接运行：

```powershell
.\build_exe.bat
```

打包完成后，exe 文件在：

```text
dist\文件服务器.exe
```
