<template>
    <v-dialog width="500" activator="parent" v-model="dialog" @update:modelValue="seedFromFinish">

        <v-card>
            <v-closable-card-title :title="$t('FinishTime')" v-model="dialog"></v-closable-card-title>

            <v-card-text>
                <p>{{ $t('FinishTimeHelp') }}</p>

                <v-row no-gutters class="mt-2">
                    <v-col cols="12" sm="7">
                        <v-select
                            v-model="weekday"
                            :items="weekdayOptions"
                            :label="$t('Day')"
                            prepend-inner-icon="$calendar"
                            hide-details>
                        </v-select>
                    </v-col>
                    <v-col cols="12" sm="5">
                        <v-text-field v-model="timeOfDay"
                                      :active="timePickerMenu" :focus="timePickerMenu"
                                      :label="$t('Time')" prepend-inner-icon="fa-solid fa-clock" readonly
                                      hide-details>
                            <v-menu v-model="timePickerMenu" :close-on-content-click="false"
                                    activator="parent" transition="scale-transition">
                                <v-time-picker v-if="timePickerMenu" format="24hr" v-model="timeOfDay"></v-time-picker>
                            </v-menu>
                        </v-text-field>
                    </v-col>
                </v-row>

                <p class="mt-4 text-grey">{{ $t('Finish') }}: {{ displayStartTime(resolvedFinish) }}</p>
            </v-card-text>

            <v-card-actions>
                <v-btn color="warning" prepend-icon="$delete" @click="emit('clear'); dialog=false" v-if="props.finish">{{ $t('Clear') }}</v-btn>
                <!-- "Apply", not "Save": this writes the finish time to the url and nothing else, there is
                     no persistence anywhere behind it (REQ-004 Decision 3) -->
                <v-btn color="save" prepend-icon="fa-solid fa-check" @click="emit('confirm', resolvedFinish); dialog=false">{{ $t('Apply') }}</v-btn>
            </v-card-actions>
        </v-card>

    </v-dialog>
</template>

<script setup lang="ts">

import {computed, PropType, ref} from 'vue'
import {DateTime, Info, WeekdayNumbers} from 'luxon'
import {useI18n} from 'vue-i18n'
import VClosableCardTitle from "@/components/dialogs/VClosableCardTitle.vue";
import {nextOccurrence} from "@/utils/schedule_utils.ts";
import {useStartTimeDisplay} from "@/composables/useStartTimeDisplay.ts";

const {locale} = useI18n()
const displayStartTime = useStartTimeDisplay()

const emit = defineEmits({
    confirm(payload: DateTime) {
        return payload
    },
    clear() {
        return true
    },
})

const props = defineProps({
    finish: {type: {} as PropType<DateTime | undefined>, required: false},
})

const dialog = ref(false)
const timePickerMenu = ref(false)

const weekday = ref<WeekdayNumbers>(DateTime.now().weekday)
const timeOfDay = ref('12:00')

/**
 * the seven weekdays named by the runtime rather than by translation keys, in ISO order so that the
 * value of an option is its ISO weekday number
 */
const weekdayOptions = computed(() => {
    return Info.weekdays('long', {locale: locale.value}).map((name, index) => ({title: name, value: (index + 1) as WeekdayNumbers}))
})

/**
 * the finish time the current picker state stands for, the next upcoming occurrence of the chosen weekday
 */
const resolvedFinish = computed(() => {
    const [hour, minute] = timeOfDay.value.split(':').map(Number)
    return nextOccurrence(weekday.value, hour ?? 12, minute ?? 0, DateTime.now())
})

/**
 * seeds the picker from the finish time in force whenever the dialog opens
 *
 * a finish time handed over by the meal plan can lie further out than the picker itself can express, its
 * weekday and time still show correctly - saving then re-snaps to the next occurrence, which is the
 * documented behaviour of touching the picker rather than an accident
 *
 * @param opened whether the dialog is opening or closing
 */
function seedFromFinish(opened: boolean) {
    if (!opened) {
        return
    }

    const finish = props.finish ?? DateTime.now().set({hour: 12, minute: 0})
    weekday.value = finish.weekday as WeekdayNumbers
    timeOfDay.value = finish.toFormat('HH:mm')
}

</script>

<style scoped>

</style>
