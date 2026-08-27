import type { Messages } from "./index";

/**
 * Ελληνικά — the Greek catalogue.
 *
 * Typed as `Messages` so a key that exists in English and not here is a compile error,
 * not a screen that quietly reverts to English in front of a Greek user.
 *
 * Conventions followed throughout, because getting them wrong is what makes a translated
 * app read as translated:
 *
 * - **Second person singular** (εσύ), matching the English tone. Greek fitness apps that
 *   use the plural/formal εσείς read like a bank.
 * - **No final -ν** except where the grammar requires it before a vowel or plosive.
 * - **Units stay Latin** — kg, cm, kcal, ml — because that is how they are written on
 *   Greek packaging and gym equipment. "χλγ" would be pedantic and nobody uses it.
 * - **Accents are kept.** Search is diacritic-insensitive server-side, but UI text is
 *   read rather than typed, and unaccented Greek prose looks like a shout.
 * - Placeholders `{name}` are positional and must survive translation untouched.
 */
export const el: Messages = {
  // ------------------------------------------------------------------ common
  "common.save": "Αποθήκευση",
  "common.cancel": "Άκυρο",
  "common.delete": "Διαγραφή",
  "common.done": "Τέλος",
  "common.retry": "Δοκίμασε ξανά",
  "common.loading": "Φόρτωση",
  "common.search": "Αναζήτηση",
  "common.today": "Σήμερα",
  "common.yesterday": "Χθες",
  "common.offline": "Είσαι εκτός σύνδεσης. Οι αλλαγές αποθηκεύονται και θα συγχρονιστούν.",
  "common.errorTitle": "Κάτι πήγε στραβά",
  "common.errorBody": "Δεν έγινε. Δοκίμασε ξανά σε λίγο.",

  // -------------------------------------------------------------------- auth
  "auth.welcomeTitle": "Προπόνηση με σκοπό",
  "auth.welcomeBody":
    "Κατέγραψε προπονήσεις, παρακολούθησε τι τρως και δες τι πραγματικά αλλάζει.",
  "auth.login": "Σύνδεση",
  "auth.register": "Δημιουργία λογαριασμού",
  "auth.email": "Email",
  "auth.password": "Κωδικός",
  "auth.name": "Όνομα",
  "auth.forgotPassword": "Ξέχασες τον κωδικό σου;",
  "auth.noAccount": "Πρώτη φορά εδώ;",
  "auth.haveAccount": "Έχεις ήδη λογαριασμό;",
  "auth.verifyTitle": "Έλεγξε το email σου",
  "auth.verifyBody": "Στείλαμε έναν σύνδεσμο στο {email}. Άνοιξέ τον για να ολοκληρώσεις.",
  "auth.logout": "Αποσύνδεση",

  // --------------------------------------------------------------------- tabs
  "tabs.home": "Αρχική",
  "tabs.workouts": "Προπονήσεις",
  "tabs.log": "Καταγραφή",
  "tabs.nutrition": "Διατροφή",
  "tabs.profile": "Προφίλ",

  // --------------------------------------------------------------------- home
  "home.greeting": "Γεια σου, {name}",
  "home.todaysCalories": "Θερμίδες σήμερα",
  "home.protein": "Πρωτεΐνη",
  "home.carbs": "Υδατάνθρακες",
  "home.fat": "Λίπος",
  "home.water": "Νερό",
  "home.weight": "Βάρος",
  "home.streak": "Σερί",
  "home.streakDays": "{count} ημέρες",
  "home.todaysWorkout": "Η προπόνηση σήμερα",
  "home.noWorkoutPlanned": "Δεν έχεις προγραμματίσει κάτι. Ξεκίνα όποτε είσαι έτοιμος.",
  "home.recentActivity": "Πρόσφατη δραστηριότητα",
  "home.nothingYet": "Δεν έχεις καταγράψει κάτι ακόμα.",

  // ----------------------------------------------------------------- workouts
  "workouts.start": "Ξεκίνα προπόνηση",
  "workouts.routines": "Προγράμματα",
  "workouts.history": "Ιστορικό",
  "workouts.active": "Σε εξέλιξη",
  "workouts.finish": "Τέλος",
  "workouts.addExercise": "Πρόσθεσε άσκηση",
  "workouts.sets": "Σετ",
  "workouts.reps": "Επαναλήψεις",
  "workouts.weight": "Βάρος",
  "workouts.rest": "Ξεκούραση",
  "workouts.restTimer": "Ξεκούραση — {seconds}δ",
  "workouts.notes": "Σημειώσεις",
  "workouts.noHistory": "Καμία προπόνηση ακόμα. Η πρώτη ξεκινά το σερί.",
  "workouts.resume": "Συνέχισε την προπόνηση",
  "workouts.newRoutine": "Νέο πρόγραμμα",
  "workouts.noRoutines": "Δεν έχεις προγράμματα. Φτιάξε ένα ή ξεκίνα από πρότυπο.",
  "workouts.templates": "Πρότυπα",
  "workouts.useTemplate": "Χρήση προτύπου",
  "workouts.startRoutine": "Ξεκίνα",
  "workouts.editRoutine": "Επεξεργασία",
  "workouts.duplicate": "Αντιγραφή",
  "workouts.unfoldered": "Χωρίς ομάδα",
  "workouts.routineName": "Όνομα προγράμματος",
  "workouts.exerciseCount": "{count} ασκήσεις",
  "workouts.setCount": "{count} σετ",
  "workouts.lastPerformed": "Τελευταία {when}",
  "workouts.neverPerformed": "Ποτέ",
  "workouts.saveRoutine": "Αποθήκευση προγράμματος",
  "workouts.deleteRoutine": "Διαγραφή προγράμματος",

  // ---------------------------------------------------------------- nutrition
  "nutrition.diary": "Ημερολόγιο",
  "nutrition.breakfast": "Πρωινό",
  "nutrition.lunch": "Μεσημεριανό",
  "nutrition.dinner": "Βραδινό",
  "nutrition.snack": "Σνακ",
  "nutrition.searchFoods": "Αναζήτηση τροφίμων",
  "nutrition.recent": "Πρόσφατα",
  "nutrition.addFood": "Πρόσθεσε τρόφιμο",
  "nutrition.quickAdd": "Γρήγορη προσθήκη",
  "nutrition.caloriesLeft": "Απομένουν {count} kcal",
  "nutrition.noTarget": "Όρισε στόχο θερμίδων για να τον παρακολουθείς.",
  "nutrition.nothingLogged": "Δεν έχεις καταγράψει κάτι.",
  "nutrition.verified": "Επιβεβαιωμένο",
  "nutrition.perHundred": "ανά 100 {unit}",
  "nutrition.previousDay": "Προηγούμενη ημέρα",
  "nutrition.nextDay": "Επόμενη ημέρα",
  "nutrition.copyPreviousDay": "Αντιγραφή προηγούμενης ημέρας",
  "nutrition.amount": "Ποσότητα",

  // ----------------------------------------------------------------- progress
  "progress.weight": "Βάρος",
  "progress.measurements": "Μετρήσεις",
  "progress.photos": "Φωτογραφίες",
  "progress.trend": "Τάση",
  "progress.logWeight": "Κατέγραψε βάρος",
  "progress.noData": "Κατέγραψε λίγες μέρες και η τάση θα εμφανιστεί εδώ.",

  // -------------------------------------------------------------------- coach
  "coach.title": "Προπονητής",
  "coach.placeholder": "Ρώτησε για την προπόνηση ή τη διατροφή σου",
  "coach.thinking": "Σκέφτεται",
  "coach.disclaimer": "Καθοδήγηση, όχι ιατρική συμβουλή.",
  "coach.empty": "Ρώτησε ό,τι θέλεις. Τα δεδομένα σου είναι ήδη στη συζήτηση.",

  // ------------------------------------------------------------------ profile
  "profile.personal": "Προσωπικά στοιχεία",
  "profile.theme": "Θέμα",
  "profile.themeSystem": "Όπως η συσκευή",
  "profile.themeDark": "Σκούρο",
  "profile.themeLight": "Ανοιχτό",
  "profile.language": "Γλώσσα",

  // ---------------------------------------------------------------- routines
  "routines.noTemplates": "Δεν υπάρχουν διαθέσιμα πρότυπα.",
  "routines.moreExercises": "+{count} ακόμα",
  "routines.removeRoutineBody": "Αυτό το πρόγραμμα θα αφαιρεθεί.",
  "routines.alreadyInProgressTitle": "Υπάρχει ήδη προπόνηση σε εξέλιξη",
  "routines.alreadyInProgressBody": "Ολοκλήρωσέ την ή απόρριψέ την πριν ξεκινήσεις άλλη.",
  "routines.estimatedMinutes": "~{count} λεπτά",
  "routines.restSeconds": "{count}δ ξεκούραση",
  "routines.setsOnly": "{count} σετ",

  // ------------------------------------------------------------ active workout
  "active.paused": "Σε παύση — πάτα για συνέχεια",
  "active.pause": "Παύση προπόνησης",
  "active.resume": "Συνέχεια προπόνησης",
  "active.moveUp": "Μετακίνησε {name} πάνω",
  "active.moveDown": "Μετακίνησε {name} κάτω",
  "active.remove": "Αφαίρεσε {name}",
  "active.removeTitle": "Αφαίρεση {name};",
  "active.removeBody": "{count} καταγεγραμμένα σετ θα διαγραφούν.",
  "active.discardTitle": "Απόρριψη της προπόνησης;",
  "active.discardBody": "{count} σετ θα διαγραφούν. Δεν αναιρείται.",
  "active.setComplete": "Σετ {number} ολοκληρώθηκε",
  "active.setCompleteRecord": "Σετ {number} ολοκληρώθηκε, προσωπικό ρεκόρ",
  "active.deleteSetHint": "Παρατεταμένο πάτημα για διαγραφή",
  "active.weightFor": "Βάρος για το σετ {number}",
  "active.repsFor": "Επαναλήψεις για το σετ {number}",
  "active.personalRecord": "Προσωπικό ρεκόρ",
  "active.oneFewerSet": "Ένα σετ λιγότερο",
  "active.oneMoreSet": "Ένα σετ ακόμα",

  // ---------------------------------------------------------------- exercises
  "exercises.noDemonstration": "Δεν υπάρχει επίδειξη ακόμα",
  "exercises.howTo": "ΕΚΤΕΛΕΣΗ",
  "exercises.muscles": "ΜΥΕΣ",
  "exercises.alsoWorks": "Επίσης: {muscles}",
  "exercises.howToDo": "Πώς γίνεται η άσκηση {name}",
  "exercises.offlineCached": "Εκτός σύνδεσης — εμφανίζονται ασκήσεις που έχεις ήδη ανοίξει.",
  "exercises.nothingMatched": "Καμία αντιστοιχία. Δοκίμασε πιο σύντομη λέξη.",

  // --------------------------------------------------------------- progress+
  "progress.title": "Πρόοδος",
  "progress.noWeighIns": "Καμία ζύγιση ακόμα",
  "progress.todaysWeight": "Βάρος σήμερα",
  "progress.todaysWeightLabel": "Το βάρος σου σήμερα σε κιλά",
  "progress.volumeByMuscle": "ΟΓΚΟΣ ΑΝΑ ΜΥΪΚΗ ΟΜΑΔΑ",
  "progress.noCompletedWorkouts": "Καμία ολοκληρωμένη προπόνηση σε αυτή την περίοδο.",
  "progress.recordMeasurements": "Κατέγραψε μετρήσεις",
  "progress.nothingRecorded":
    "Καμία μέτρηση ακόμα. Μέση και μπράτσα είναι αυτά που παρακολουθούν οι περισσότεροι.",
  "progress.onlyWhatYouMeasured":
    "Συμπλήρωσε μόνο όσα μέτρησες. Ό,τι αφήσεις κενό κρατά την προηγούμενη τιμή του.",
  "progress.checkValue": "Έλεγξε αυτή την τιμή",
  "progress.notANumber": "Αυτή η τιμή δεν είναι αριθμός.",
  "progress.onTrack": "Σε καλό δρόμο για {weight} kg γύρω στις {date}",
  "progress.movingAway": "Η τάση απομακρύνεται από τον στόχο σου.",
  "progress.kgTrend": "kg τάση",
  "progress.centimetres": "{name} σε εκατοστά",

  // -------------------------------------------------------------------- goals
  "goals.title": "Στόχος",
  "goals.targetWeight": "Στόχος βάρους",
  "goals.weeklyRate": "Ρυθμός ανά εβδομάδα",
  "goals.targetWeightLabel": "Στόχος βάρους σε κιλά",
  "goals.weeklyRateLabel": "Ρυθμός ανά εβδομάδα σε κιλά",
  "goals.currentTargets": "ΗΜΕΡΗΣΙΟΙ ΣΤΟΧΟΙ",
  "goals.saveAndRecalculate": "Αποθήκευση και επανυπολογισμός",
  "goals.recalculateNote":
    "Η αποθήκευση επανυπολογίζει τους ημερήσιους στόχους από το προφίλ, το τρέχον βάρος και αυτόν τον στόχο.",
  "goals.clampedTitle": "Οι στόχοι ανέβηκαν σε ασφαλές όριο",
  "goals.clampedBody":
    "Το έλλειμμα που ζήτησες ήταν κάτω από το ελάχιστο που ορίζουμε, οπότε οι θερμίδες σου ανέβηκαν. Διάλεξε πιο αργό ρυθμό αν θέλεις το έλλειμμα που είχες στο μυαλό σου.",
  "goals.checkWeight": "Έλεγξε το βάρος",
  "goals.weightNotANumber": "Ο στόχος βάρους δεν είναι αριθμός.",
  "goals.notSet": "Δεν έχει οριστεί",
  "goals.loseFat": "Απώλεια λίπους",
  "goals.maintain": "Διατήρηση",
  "goals.gainMuscle": "Αύξηση μυϊκής μάζας",
  "goals.recomp": "Ανασύνθεση",
  "goals.performance": "Απόδοση",
  "goals.loseFatBlurb":
    "Έλλειμμα θερμίδων, με υψηλή πρωτεΐνη ώστε να κρατήσεις τους μυς που έχεις.",
  "goals.maintainBlurb":
    "Κράτα το βάρος σου. Οι στόχοι παρακολουθούν την πρόσληψη αντί να την πιέζουν.",
  "goals.gainMuscleBlurb": "Μικρό πλεόνασμα. Πιο γρήγορα σημαίνει κυρίως λίπος, όχι μυς.",
  "goals.recompBlurb": "Τρώγε στη συντήρηση και προπονήσου σκληρά. Αργό, αλλά δουλεύει.",
  "goals.performanceBlurb": "Τροφοδοσία για απόδοση, όχι για τη ζυγαριά.",

  // ------------------------------------------------------------- achievements
  "achievements.title": "Επιτεύγματα",
  "achievements.earnedOf": "{earned} από {total}",
  "achievements.badgesAndStreaks": "Διακρίσεις και σερί",
  "achievements.consistency": "Συνέπεια",
  "achievements.volume": "Όγκος",
  "achievements.strength": "Δύναμη",
  "achievements.milestone": "Ορόσημα",

  // ------------------------------------------------------------------- coach+
  "coach.askTheCoach": "Ρώτησε τον προπονητή",
  "coach.messageLabel": "Μήνυμα στον προπονητή",
  "coach.send": "Αποστολή",
  "coach.supportNotCoaching": "Υποστήριξη, όχι καθοδήγηση",
  "coach.emptyPrompt": "Ρώτησε για την προπόνηση, τη διατροφή ή το επόμενο βήμα σου.",
  "coach.emptyHint": "Ο προπονητής βλέπει τις προπονήσεις, το βάρος και το ημερολόγιό σου.",
  "coach.leftToday": "Απομένουν {count} σήμερα",
  "coach.noneLeftToday": "Δεν απομένουν μηνύματα σήμερα",
  "coach.quotaSpent": "Εξάντλησες τα μηνύματα καθοδήγησης για σήμερα.",
  "coach.unavailable": "Ο προπονητής δεν είναι διαθέσιμος τώρα. Δοκίμασε σύντομα.",
  "coach.needsConnection": "Δεν υπάρχει σύνδεση. Ο προπονητής τη χρειάζεται.",
  "coach.tooLong": "Ο προπονητής άργησε πολύ να απαντήσει.",
  "coach.helpful": "Χρήσιμο",
  "coach.dismiss": "Απόρριψη",

  // ------------------------------------------------------------- notifications
  "notifications.title": "Ειδοποιήσεις",
  "notifications.unreadCount": "{count} μη αναγνωσμένες",
  "notifications.markAllRead": "Σήμανση όλων ως αναγνωσμένων",
  "notifications.emptyTitle": "Τίποτα ακόμα.",
  "notifications.emptyBody":
    "Υπενθυμίσεις, ρεκόρ και παρατηρήσεις του προπονητή έρχονται εδώ.",
  "notifications.settings": "Ρυθμίσεις ειδοποιήσεων",
  "notifications.delivery": "ΠΑΡΑΔΟΣΗ",
  "notifications.whatToSend": "ΤΙ ΣΤΕΛΝΟΥΜΕ",
  "notifications.quietHours": "ΩΡΕΣ ΗΣΥΧΙΑΣ",
  "notifications.quietHoursBody":
    "Τίποτα δεν παραδίδεται αυτές τις ώρες. Φτάνει μετά, αντί να χαθεί.",
  "notifications.alwaysSent": "Τα μηνύματα λογαριασμού και ασφάλειας στέλνονται πάντα.",
  "notifications.push": "Ειδοποιήσεις push",
  "notifications.pushOnThisDevice": "Σε αυτή τη συσκευή.",
  "notifications.pushNeedsPermission": "Επίτρεψε τις ειδοποιήσεις παραπάνω για να ισχύσει.",
  "notifications.email": "Email",
  "notifications.emailDetail": "Εβδομαδιαίες συνόψεις και μηνύματα λογαριασμού.",
  "notifications.turnOn": "ΕΝΕΡΓΟΠΟΙΗΣΗ ΕΙΔΟΠΟΙΗΣΕΩΝ",
  "notifications.permissionPitch":
    "Θα σου πούμε όταν σπας ρεκόρ, όταν ένα σερί κινδυνεύει και όταν ο προπονητής παρατηρήσει κάτι. Τίποτα άλλο.",
  "notifications.permissionDenied":
    "Οι ειδοποιήσεις για το CoreSync είναι κλειστές στις ρυθμίσεις της συσκευής σου. Μπορείς να τις ανοίξεις από εκεί.",
  "notifications.permissionUnsupported":
    "Αυτή η συσκευή δεν μπορεί να λάβει ειδοποιήσεις push. Ένας εξομοιωτής ποτέ δεν μπορεί.",
  "notifications.allow": "Επίτρεψε ειδοποιήσεις",
  "notifications.asking": "Ερώτηση…",
  "notifications.openSettings": "Άνοιξε τις ρυθμίσεις",
  "notifications.off": "Κλειστό",
  "notifications.categoryWorkoutReminder": "Υπενθυμίσεις προπόνησης",
  "notifications.categoryPrCelebration": "Προσωπικά ρεκόρ",
  "notifications.categoryStreakRisk": "Σερί σε κίνδυνο",
  "notifications.categoryInsightReady": "Παρατηρήσεις προπονητή",
  "notifications.categoryWeeklyReport": "Εβδομαδιαία αναφορά",
  "notifications.blurbWorkoutReminder": "Μια υπενθύμιση τις μέρες που συνήθως προπονείσαι.",
  "notifications.blurbPrCelebration": "Όταν σπας ένα ρεκόρ.",
  "notifications.blurbStreakRisk": "Πριν χαθεί ένα σερί που έχτισες.",
  "notifications.blurbInsightReady": "Όταν ο προπονητής παρατηρήσει κάτι.",
  "notifications.blurbWeeklyReport": "Μια σύνοψη της εβδομάδας, μία φορά την εβδομάδα.",

  // ----------------------------------------------------------------- settings
  "settings.title": "Ρυθμίσεις",
  "settings.units": "ΜΟΝΑΔΕΣ",
  "settings.metric": "Μετρικό (kg, cm)",
  "settings.imperial": "Imperial (lb, ft)",
  "settings.privacy": "ΑΠΟΡΡΗΤΟ",
  "settings.improveCoach": "Βελτίωση του προπονητή",
  "settings.improveCoachDetail":
    "Επίτρεψε τις ανώνυμες συζητήσεις σου να βελτιώσουν το μοντέλο. Κλειστό από προεπιλογή.",
  "settings.productEmails": "Email προϊόντος",
  "settings.productEmailsDetail":
    "Περιστασιακές ενημερώσεις. Δεν απαιτούνται για μηνύματα λογαριασμού.",
  "settings.privacyPolicy": "Πολιτική απορρήτου",
  "settings.account": "ΛΟΓΑΡΙΑΣΜΟΣ",
  "settings.deleteAccount": "Διαγραφή λογαριασμού",
  "settings.deleteAccountLabel": "Διέγραψε τον λογαριασμό σου",
  "settings.deleteTitle": "Διαγραφή του λογαριασμού σου;",
  "settings.deleteBody":
    "Θα αποσυνδεθείς παντού αμέσως. Τα δεδομένα σου κρατούνται για 30 ημέρες — συνδέσου ξανά μέσα σε αυτό το διάστημα για ακύρωση. Μετά τις 30 ημέρες διαγράφονται οριστικά.",
  "settings.deleteScheduled": "Ο λογαριασμός προγραμματίστηκε για διαγραφή",
  "settings.working": "Γίνεται…",
  "settings.plan": "ΠΛΑΝΟ",
  "settings.goalAndTargets": "Στόχος και ημερήσιοι στόχοι",
  "settings.progressDetail": "Βάρος, μετρήσεις, όγκος",
  "settings.app": "ΕΦΑΡΜΟΓΗ",
  "settings.notificationsDetail": "Τι στέλνουμε, και πότε",
  "settings.settingsDetail": "Μονάδες, απόρρητο, λογαριασμός",

  // -------------------------------------------------------------- profile edit
  "profileEdit.title": "Προφίλ",
  "profileEdit.displayName": "Όνομα εμφάνισης",
  "profileEdit.yourName": "Το όνομά σου",
  "profileEdit.height": "Ύψος",
  "profileEdit.activity": "ΔΡΑΣΤΗΡΙΟΤΗΤΑ",
  "profileEdit.activityDetail":
    "Πόσο κινείσαι εκτός προπόνησης. Αυτό τροφοδοτεί τους στόχους θερμίδων σου.",
  "profileEdit.experience": "ΕΜΠΕΙΡΙΑ",
  "profileEdit.bio": "ΒΙΟΓΡΑΦΙΚΟ",
  "profileEdit.optional": "Προαιρετικό",
  "profileEdit.nameRequired": "Απαιτείται όνομα",
  "profileEdit.nameEmpty": "Το όνομα εμφάνισης δεν μπορεί να είναι κενό.",
  "profileEdit.checkHeight": "Έλεγξε το ύψος σου",
  "profileEdit.heightNotANumber": "Αυτό δεν είναι αριθμός.",
  "profileEdit.years": "{count} ετών",
  "profileEdit.sedentary": "Καθιστική",
  "profileEdit.light": "Ελαφρώς ενεργός",
  "profileEdit.moderate": "Μέτρια ενεργός",
  "profileEdit.active": "Ενεργός",
  "profileEdit.veryActive": "Πολύ ενεργός",
  "profileEdit.beginner": "Αρχάριος",
  "profileEdit.intermediate": "Μέσου επιπέδου",
  "profileEdit.advanced": "Προχωρημένος",

  // ------------------------------------------------------------------ apple
  "apple.signInFailed": "Η σύνδεση με Apple δεν ολοκληρώθηκε. Δοκίμασε ξανά.",
  "apple.noToken": "Η Apple δεν επέστρεψε διακριτικό σύνδεσης.",
  "apple.needsConnection": "Δεν υπάρχει σύνδεση. Η σύνδεση με Apple τη χρειάζεται.",
  "apple.or": "ή",
  "apple.signingIn": "Σύνδεση…",

  // ----------------------------------------------------------------- history
  "history.duration": "Διάρκεια",
  "history.volume": "Όγκος",
  "history.sets": "σετ",
  "history.set": "σετ",
  "history.justNow": "μόλις τώρα",
  "history.minutesAgo": "πριν {count} λ.",
  "history.hoursAgo": "πριν {count} ώρ.",
  "history.daysAgo": "πριν {count} ημ.",

  // --------------------------------------------------------------- calendar
  "calendar.title": "Ημερολόγιο",
  "calendar.previousMonth": "Προηγούμενος μήνας",
  "calendar.nextMonth": "Επόμενος μήνας",
  "calendar.daysTrained": "ημέρες προπόνησης",
  "calendar.hours": "ώρες",
  "calendar.dayTrained": "{date}, {count} προπονήσεις",
  "calendar.dayRest": "{date}, ημέρα ξεκούρασης",
};
