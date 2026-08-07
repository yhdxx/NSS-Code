---
name: java-docs
description: 用于“Java 文档”的工程工作流。适用于后端语言与框架、代码库理解与工程规划相关的代码开发、测试、调试、集成与维护任务。
---
## 中文摘要
用于“Java 文档”的工程工作流。适用于后端语言与框架、代码库理解与工程规划相关的代码开发、测试、调试、集成与维护任务。


# Java Documentation (Javadoc) Best Practices

- Public and protected members should be documented with Javadoc comments.
- It is encouraged to document package-private and private members as well, especially if they are complex or not self-explanatory.
- The first sentence of the Javadoc comment is the summary description. It should be a concise overview of what the method does and end with a period.
- Use `@param` for method parameters. The description starts with a lowercase letter and does not end with a period.
- Use `@return` for method return values.
- Use `@throws` or `@exception` to document exceptions thrown by methods.
- Use `@see` for references to other types or members.
- Use `{@inheritDoc}` to inherit documentation from base classes or interfaces.
  - Unless there is major behavior change, in which case you should document the differences.
- Use `@param <T>` for type parameters in generic types or methods.
- Use `{@code}` for inline code snippets.
- Use `<pre>{@code ... }</pre>` for code blocks.
- Use `@since` to indicate when the feature was introduced (e.g., version number).
- Use `@version` to specify the version of the member.
- Use `@author` to specify the author of the code.
- Use `@deprecated` to mark a member as deprecated and provide an alternative.
