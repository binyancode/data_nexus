git add .
set /p commit_msg="Please enter commit message: "
git commit -m "%commit_msg%"
git branch -M main
git remote remove origin 2>nul
git remote add origin https://github.com/binyancode/data_nexus.git
git push -u origin main
