if __name__ == "__main__":
    import asyncio

    from mycodingagent.configuration.bootstrap import bootstrap_user_config

    bootstrap_result = bootstrap_user_config()
    for message in [*bootstrap_result.messages, *bootstrap_result.warnings]:
        print(message, flush=True)
    if bootstrap_result.fatal_error:
        print(bootstrap_result.fatal_error, flush=True)
        raise SystemExit(1)

    from mycodingagent.app.main import main

    asyncio.run(main())
