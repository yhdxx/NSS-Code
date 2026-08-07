---
name: next-intl-add-language
description: 用于“Next.js 国际化 添加 language”的工程工作流。适用于通用代码开发相关的代码开发、测试、调试、集成与维护任务。
---
## 中文摘要
用于“Next.js 国际化 添加 language”的工程工作流。适用于通用代码开发相关的代码开发、测试、调试、集成与维护任务。


This is a guide to add a new language to a Next.js project using next-intl for internationalization,

- For i18n, the application uses next-intl.
- All translations are in the directory `./messages`.
- The UI component is `src/components/language-toggle.tsx`.
- Routing and middleware configuration are handled in:
  - `src/i18n/routing.ts`
  - `src/middleware.ts`

When adding a new language:

- Translate all the content of `en.json` to the new language. The goal is to have all the JSON entries in the new language for a complete translation.
- Add the path in `routing.ts` and `middleware.ts`.
- Add the language to `language-toggle.tsx`.
