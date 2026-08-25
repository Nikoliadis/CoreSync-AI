/**
 * English strings. The reference catalogue — every other locale is checked against it.
 *
 * Keys are `area.thing`, flat rather than nested, so a missing translation is a single
 * lookup miss instead of an undefined path. `{name}` placeholders are substituted by
 * `t()`.
 *
 * The tone is the product's: short, direct, second person, no exclamation marks. A gym
 * app that cheers at you between sets gets deleted.
 */
export const en = {
  // ------------------------------------------------------------------ common
  "common.save": "Save",
  "common.cancel": "Cancel",
  "common.delete": "Delete",
  "common.done": "Done",
  "common.retry": "Try again",
  "common.loading": "Loading",
  "common.search": "Search",
  "common.today": "Today",
  "common.yesterday": "Yesterday",
  "common.offline": "You're offline. Changes are saved and will sync.",
  "common.errorTitle": "Something went wrong",
  "common.errorBody": "That didn't work. Try again in a moment.",

  // -------------------------------------------------------------------- auth
  "auth.welcomeTitle": "Train with intent",
  "auth.welcomeBody": "Log workouts, track what you eat, and see what actually changes.",
  "auth.login": "Log in",
  "auth.register": "Create account",
  "auth.email": "Email",
  "auth.password": "Password",
  "auth.name": "Name",
  "auth.forgotPassword": "Forgot your password?",
  "auth.noAccount": "New here?",
  "auth.haveAccount": "Already have an account?",
  "auth.verifyTitle": "Check your email",
  "auth.verifyBody": "We sent a link to {email}. Open it to finish setting up.",
  "auth.logout": "Log out",

  // --------------------------------------------------------------------- tabs
  "tabs.home": "Home",
  "tabs.workouts": "Workouts",
  "tabs.log": "Log",
  "tabs.nutrition": "Nutrition",
  "tabs.profile": "Profile",

  // --------------------------------------------------------------------- home
  "home.greeting": "Hello, {name}",
  "home.todaysCalories": "Calories today",
  "home.protein": "Protein",
  "home.carbs": "Carbs",
  "home.fat": "Fat",
  "home.water": "Water",
  "home.weight": "Weight",
  "home.streak": "Streak",
  "home.streakDays": "{count} days",
  "home.todaysWorkout": "Today's workout",
  "home.noWorkoutPlanned": "Nothing planned. Start one whenever you're ready.",
  "home.recentActivity": "Recent activity",
  "home.nothingYet": "Nothing logged yet.",

  // ----------------------------------------------------------------- workouts
  "workouts.start": "Start workout",
  "workouts.routines": "Routines",
  "workouts.history": "History",
  "workouts.active": "In progress",
  "workouts.finish": "Finish",
  "workouts.addExercise": "Add exercise",
  "workouts.sets": "Sets",
  "workouts.reps": "Reps",
  "workouts.weight": "Weight",
  "workouts.rest": "Rest",
  "workouts.restTimer": "Resting — {seconds}s",
  "workouts.notes": "Notes",
  "workouts.noHistory": "No workouts yet. Your first one starts the streak.",
  "workouts.resume": "Resume workout",
  "workouts.newRoutine": "New routine",
  "workouts.noRoutines": "No routines yet. Build one, or start from a template.",
  "workouts.templates": "Templates",
  "workouts.useTemplate": "Use this template",
  "workouts.startRoutine": "Start",
  "workouts.editRoutine": "Edit",
  "workouts.duplicate": "Duplicate",
  "workouts.unfoldered": "Ungrouped",
  "workouts.routineName": "Routine name",
  "workouts.exerciseCount": "{count} exercises",
  "workouts.setCount": "{count} sets",
  "workouts.lastPerformed": "Last done {when}",
  "workouts.neverPerformed": "Never done",
  "workouts.saveRoutine": "Save routine",
  "workouts.deleteRoutine": "Delete routine",

  // ---------------------------------------------------------------- nutrition
  "nutrition.diary": "Diary",
  "nutrition.breakfast": "Breakfast",
  "nutrition.lunch": "Lunch",
  "nutrition.dinner": "Dinner",
  "nutrition.snack": "Snacks",
  "nutrition.searchFoods": "Search foods",
  "nutrition.recent": "Recent",
  "nutrition.addFood": "Add food",
  "nutrition.quickAdd": "Quick add",
  "nutrition.caloriesLeft": "{count} kcal left",
  "nutrition.noTarget": "Set a calorie target to track against it.",
  "nutrition.nothingLogged": "Nothing logged.",
  "nutrition.verified": "Verified",
  "nutrition.perHundred": "per 100 {unit}",

  // ----------------------------------------------------------------- progress
  "progress.weight": "Weight",
  "progress.measurements": "Measurements",
  "progress.photos": "Photos",
  "progress.trend": "Trend",
  "progress.logWeight": "Log weight",
  "progress.noData": "Log a few days and the trend appears here.",

  // -------------------------------------------------------------------- coach
  "coach.title": "Coach",
  "coach.placeholder": "Ask about your training or your diet",
  "coach.thinking": "Thinking",
  "coach.disclaimer": "Guidance, not medical advice.",
  "coach.empty": "Ask anything. Your logged data is already in the conversation.",

  // ------------------------------------------------------------------ profile
  "profile.personal": "Personal information",
  "profile.goals": "Goals",
  "profile.activityLevel": "Activity level",
  "profile.units": "Units",
  "profile.notifications": "Notifications",
  "profile.theme": "Theme",
  "profile.themeSystem": "Match device",
  "profile.themeDark": "Dark",
  "profile.themeLight": "Light",
  "profile.language": "Language",
  "profile.privacy": "Privacy",
  "profile.account": "Account",
} satisfies Record<string, string>;
