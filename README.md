# About

This is a moderation bot to help synchronize bans of spam/abusive accounts across different Reddit communities. With the deprecation of bot detection bots like u/BotDefense, synchronizing bans of automated spammers and abusive users across different moderated communities has become more difficult. Ada helps fix that.

# What This Bot Does

When an account is banned on a subreddit and a specific keyword is included in the ban mod note, an Ada instance will:

* Ban the account from all the other subreddits it moderates.
* Generate an account report for spam and abuse.
* Notify the original banning moderator with the report.

# How to Use This Bot

1. Fill out `_auth.yaml` with the bot account and script information. Designate a subreddit on which the main ban list will be stored. The bot will automatically generate the ban list page when it's run.
2. When banning an account, include include the keyword (by default, it's `ADA` in all-caps) in their mod note, not the message sent to the user. It can be anywhere, even as a random prefix or suffix (e.g. `Spam Bot ADA` or `ADA Spammer`).
3. The bot will pick up on that ban and apply it to all other subreddits it mods, and add it to its main ban list. Those bans will have the mod note `Banned from ADA main list`.
4. If an account is problematic to ban (suspended accounts are difficult to ban, for example) they can be moved to the "ignore" list on the main ban list.

# Notes

* Personally, I run Ada with a cron job for every five minutes. `*/5 * * * *`
* Currently, I have not yet built anything for "soft-banning", but the ability to designate a ban as such is there until I build that.
* There is no way to automatically *un-ban* accounts banned through Ada. That'll have to be manually done. 
