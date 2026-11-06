-- Common staples each person's food library starts with. Values are typical ones per 100 g (or 100 ml),
-- from standard food tables, and are approximations: brands and recipes differ, so edit them to match yours.
--
-- food_seed is a template, not anyone's data. food_seed_library(user) copies it, with the seven built-in
-- nutrients, into one person's library. It runs when a person is created, and below for anyone who already
-- exists. Copies are ordinary foods: editing or deleting one changes nothing else.
--
-- Copied ids are fixed (an MD5 of the person and the food), so running it twice adds nothing and an import can
-- recognise a seeded food. changed_at is old on purpose, so your first edit always wins whatever the phone's
-- clock says (see 0005_food.sql).

create table food_seed (
  key          text primary key,
  name         text not null,
  base         text not null check (base in ('g', 'ml')),
  default_unit text not null,
  nutrients    jsonb not null,
  units        jsonb not null default '{}'::jsonb,
  notes        text
);

insert into food_seed (key, name, base, default_unit, nutrients, units, notes)
select s.key, s.name, s.base, s.default_unit,
       jsonb_build_object('kcal', s.kcal, 'protein', s.protein, 'carbs', s.carbs, 'fat', s.fat,
                          'sodium', s.sodium, 'potassium', s.potassium, 'magnesium', s.magnesium),
       s.units::jsonb, s.notes
from (values
  ('egg',            'Egg, whole',                   'g',  'piece',  143, 12.6,  0.7,   9.5, 142, 138,  12, '{"piece": 50}', 'A large egg is about 50 g without its shell.'),
  ('egg_white',      'Egg white',                    'g',  'piece',   52, 10.9,  0.7,   0.2, 166, 163,  11, '{"piece": 33}', null),
  ('rice_white',     'Rice, white, cooked',          'g',  'katori', 130,  2.7, 28.2,   0.3,   1,  35,  12, '{"katori": 150, "cup": 158}', null),
  ('rice_brown',     'Rice, brown, cooked',          'g',  'katori', 123,  2.7, 25.6,   1.0,   4,  86,  39, '{"katori": 150, "cup": 195}', null),
  ('roti',           'Roti, whole wheat',            'g',  'piece',  300,  9.8, 46.4,   8.6, 220, 200,  70, '{"piece": 40}', 'Made with a little oil and salt. A plain phulka is lighter.'),
  ('dal',            'Dal, cooked',                  'g',  'katori', 116,  9.0, 20.1,   0.4,   2, 369,  36, '{"katori": 150, "cup": 200}', 'Plain cooked lentils with no salt, oil or tadka. Edit to match how you make it.'),
  ('rajma',          'Rajma, cooked',                'g',  'katori', 127,  8.7, 22.8,   0.5,   1, 405,  45, '{"katori": 150}', 'Plain cooked kidney beans with no salt or oil.'),
  ('chana',          'Chickpeas (chana), cooked',    'g',  'katori', 164,  8.9, 27.4,   2.6,   7, 291,  48, '{"katori": 150}', 'Plain cooked chickpeas with no salt or oil.'),
  ('chicken_cooked', 'Chicken breast, cooked',       'g',  'g',      165, 31.0,  0,     3.6,  74, 256,  29, '{}', 'Skinless, grilled or roasted without oil.'),
  ('chicken_raw',    'Chicken breast, raw',          'g',  'g',      120, 22.5,  0,     2.6,  45, 334,  28, '{}', 'Skinless. Weigh before cooking.'),
  ('paneer',         'Paneer',                       'g',  'g',      265, 18.3,  1.2,  20.8,  20, 104,   8, '{}', 'Full-fat.'),
  ('milk',           'Milk, toned (3% fat)',         'ml', 'glass',   58,  3.1,  4.7,   3.0,  45, 140,  11, '{"glass": 250, "cup": 240}', null),
  ('curd',           'Curd (dahi)',                  'g',  'katori',  61,  3.5,  4.7,   3.3,  46, 155,  12, '{"katori": 150, "cup": 245}', 'Made from whole milk.'),
  ('greek_yogurt',   'Greek yogurt, plain, non-fat', 'g',  'g',       59, 10.2,  3.6,   0.4,  36, 141,  11, '{"cup": 245}', null),
  ('whey',           'Whey protein powder',          'g',  'scoop',  400, 78.0,  8.0,   6.0, 200, 500, 100, '{"scoop": 30}', 'Varies a lot by brand. Scan your tub''s barcode for its real values.'),
  ('oats',           'Oats, rolled, dry',            'g',  'g',      379, 13.2, 67.7,   6.5,   6, 362, 138, '{"cup": 81}', null),
  ('banana',         'Banana',                       'g',  'piece',   89,  1.1, 22.8,   0.3,   1, 358,  27, '{"piece": 118}', 'A medium banana is about 118 g peeled.'),
  ('apple',          'Apple',                        'g',  'piece',   52,  0.3, 13.8,   0.2,   1, 107,   5, '{"piece": 182}', null),
  ('orange',         'Orange',                       'g',  'piece',   47,  0.9, 11.8,   0.1,   0, 181,  10, '{"piece": 131}', null),
  ('dates',          'Dates',                        'g',  'piece',  277,  1.8, 75.0,   0.2,   1, 696,  54, '{"piece": 24}', 'Medjool, pitted.'),
  ('peanut_butter',  'Peanut butter',                'g',  'tbsp',   588, 25.1, 19.6,  50.4, 459, 649, 154, '{"tbsp": 16}', 'Smooth, salted.'),
  ('almonds',        'Almonds',                      'g',  'g',      579, 21.2, 21.6,  49.9,   1, 733, 270, '{"piece": 1.2, "handful": 28}', null),
  ('peanuts',        'Peanuts, roasted',             'g',  'g',      585, 24.4, 21.3,  49.7,   6, 634, 176, '{"handful": 28}', 'Dry-roasted, unsalted.'),
  ('bread',          'Bread, whole wheat',           'g',  'slice',  252, 12.4, 42.7,   3.5, 450, 250,  76, '{"slice": 32}', null),
  ('potato',         'Potato, boiled',               'g',  'piece',   87,  1.9, 20.1,   0.1,   4, 379,  22, '{"piece": 150}', 'No salt.'),
  ('sweet_potato',   'Sweet potato, baked',          'g',  'piece',   90,  2.0, 20.7,   0.2,  36, 475,  27, '{"piece": 130}', null),
  ('ghee',           'Ghee',                         'g',  'tsp',    876,  0.3,  0,    99.5,   2,   5,   0, '{"tsp": 5, "tbsp": 14}', null),
  ('olive_oil',      'Olive oil',                    'g',  'tbsp',   884,  0,    0,   100,     2,   1,   0, '{"tsp": 4.5, "tbsp": 13.5}', null),
  ('honey',          'Honey',                        'g',  'tbsp',   304,  0.3, 82.4,   0,     4,  52,   2, '{"tsp": 7, "tbsp": 21}', null),
  ('coconut_water',  'Coconut water',                'ml', 'glass',   19,  0.7,  3.7,   0.2, 105, 250,  25, '{"glass": 250}', null)
) as s(key, name, base, default_unit, kcal, protein, carbs, fat, sodium, potassium, magnesium, units, notes);

create function food_seed_library(target uuid) returns void language sql as $$
  insert into food_nutrient (user_id, id, name, unit, built_in, sort_order, changed_at)
  select target, n.id, n.name, n.unit, true, n.sort_order, '2000-01-01T00:00:00Z'::timestamptz
  from (values ('kcal', 'Calories', 'kcal', 0), ('protein', 'Protein', 'g', 1), ('carbs', 'Carbs', 'g', 2),
               ('fat', 'Fat', 'g', 3), ('sodium', 'Sodium', 'mg', 4), ('potassium', 'Potassium', 'mg', 5),
               ('magnesium', 'Magnesium', 'mg', 6)) as n(id, name, unit, sort_order)
  on conflict do nothing;

  insert into food (user_id, id, name, base, default_unit, nutrients, source, notes, changed_at)
  select target, md5(target::text || ':' || s.key)::uuid, s.name, s.base, s.default_unit, s.nutrients, 'seed',
         s.notes, '2000-01-01T00:00:00Z'::timestamptz
  from food_seed s
  on conflict do nothing;

  insert into food_unit (user_id, food_id, name, amount)
  select target, md5(target::text || ':' || s.key)::uuid, u.key, u.value::double precision
  from food_seed s cross join jsonb_each_text(s.units) as u
  on conflict do nothing;
$$;

select food_seed_library(id) from app_user;

alter table food_seed enable row level security;
do $$
declare
  r record;
begin
  for r in select rolname from pg_roles where rolname in ('anon', 'authenticated') loop
    execute format('revoke all on food_seed from %I', r.rolname);
    execute format('revoke all on function food_seed_library(uuid) from %I', r.rolname);
  end loop;
  -- Functions can be run by anyone unless taken away, and this one writes.
  revoke all on function food_seed_library(uuid) from public;
end
$$;
