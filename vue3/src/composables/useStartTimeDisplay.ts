import {useI18n} from 'vue-i18n'
import {DateTime} from 'luxon'
import {formatStartTime} from '@/utils/schedule_utils'

export type StartTimeDisplay = (start: DateTime) => string

/**
 * binds the shared start time formatter to the active locale and to now, for use at the read only
 * schedule displays (the recipe times row, the step headers)
 *
 * the reference is taken per call rather than once, so a page left open overnight renders the right
 * relative day the next time anything re-renders
 *
 * @returns a function rendering the start of a step for display
 */
export function useStartTimeDisplay(): StartTimeDisplay {
    const {t, locale} = useI18n()

    return (start: DateTime) => formatStartTime(
        start.setLocale(locale.value),
        DateTime.now(),
        {today: t('Today'), tomorrow: t('Tomorrow')},
    )
}
