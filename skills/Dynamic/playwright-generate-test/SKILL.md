---
name: playwright-generate-test
description: 用于“Playwright generate 测试”的工程工作流。适用于测试与质量保障、前端与 Web 开发相关的代码开发、测试、调试、集成与维护任务。
---
## 中文摘要
用于“Playwright generate 测试”的工程工作流。适用于测试与质量保障、前端与 Web 开发相关的代码开发、测试、调试、集成与维护任务。


# Test Generation with Playwright MCP

Your goal is to generate a Playwright test based on the provided scenario after completing all prescribed steps.

## Specific Instructions

- You are given a scenario, and you need to generate a playwright test for it. If the user does not provide a scenario, you will ask them to provide one.
- DO NOT generate test code prematurely or based solely on the scenario without completing all prescribed steps.
- DO run steps one by one using the tools provided by the Playwright MCP.
- Only after all steps are completed, emit a Playwright TypeScript test that uses `@playwright/test` based on message history
- Save generated test file in the tests directory
- Execute the test file and iterate until the test passes
