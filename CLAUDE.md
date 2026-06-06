# 自动化工作流规范

- 每次修改代码后，必须运行相关的单元测试。
- 确认测试通过且无 lint 错误后，自动生成符合规范的 commit message 并提交。
- 提交前必须确保编译通过，禁止提交包含 TODO 或 FIXME 的未完成代码。

## 提交流程

当完成一轮代码修改后（lint 和测试均通过），必须：
1. 提示用户确认是否提交到 GitHub
2. 用户确认后，生成规范的 commit message 并执行 `git commit`
3. 执行 `git push origin main` 推送到远程仓库
4. 然后再继续后续工作
