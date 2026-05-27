# PyQt6 文件服务器

一个简单的桌面文件服务器工具，可以添加一个或多个要开放的文件夹，启动后在局域网内通过浏览器访问文件。

程序同一时间只允许启动一个实例，重复打开时会提示已经在运行。

## 运行

```powershell
python app.py
```

如果缺少 PyQt6：

```powershell
python -m pip install -r requirements.txt
```

## 使用

1. 点击“添加文件夹”，可以添加多个共享文件夹；选中文件夹后可点击“移除选中”。
2. 设置端口，默认是 `8000`。
3. 设置下载限速，可选择 `KB/s` 或 `MB/s`；设为 `0` 时不限速。限速是整体共享速度，多人同时下载时会共用这一个速度上限。
4. 点击“启动”。
5. 使用界面中显示的地址访问文件，浏览器首页会显示所有共享文件夹。
6. 在浏览器目录页面里，点击文件夹右侧的“下载文件夹”可以下载 zip。
7. 共享文件夹列表会在程序同目录保存到 `settings.ini`，下次打开会自动读取。
8. 点击窗口关闭按钮会最小化到托盘；右键托盘图标可以退出。

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
