-- What auto food targets are worked out from: sex, year born, height, weight, how active the day is, a typical
-- workout and the goal. Personal, so it lives with the person's other food settings, behind the same row-level
-- security. Empty until the person fills it in.
alter table food_setting add column profile jsonb not null default '{}'::jsonb;
