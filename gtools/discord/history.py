import discord

SnowflakeTime = discord.Object


class HistoryFetcher:

    async def fetch(
        self,
        channel: discord.TextChannel,
        lower_bound: SnowflakeTime | None = None,
        upper_bound: SnowflakeTime | None = None,
    ) -> list[discord.Message]:
        messages: list[discord.Message] = []

        # oldest_first = False
        # if lower_bound is None and upper_bound is not None:
        #     oldest_first = False
        # elif lower_bound is not None and upper_bound is None:
        #     oldest_first = True
        # else:
        #     oldest_first = True

        async for m in channel.history(
            limit=1000,
            after=lower_bound,
            before=upper_bound,
            oldest_first=False,
        ):
            messages.append(m)

        return messages
