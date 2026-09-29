# Speediance app API routes (static extraction from libapp.so, app build pulled 2026-09-29)

Route strings only; request shapes unknown. Trailing stray letters (e.g. 'monthNewJ') are string-table artifacts.

## accessories
- app/accessories/list
- app/accessories/listByDeviceTypes
- mobile/accessories/list
- mobile/accessories/user/list
- mobile/accessories/user/manage

## actionLibrary
- app/actionLibrary/category
- app/actionLibrary/custom
- app/actionLibrary/custom/checkBindTemplate
- mobile/actionLibrary/ropePosition/listByDeviceType

## actionLibraryGroup
- app/actionLibraryGroup
- app/actionLibraryGroup/count
- app/actionLibraryGroup/favorites
- app/actionLibraryGroup/list
- app/actionLibraryGroup/search
- app/actionLibraryGroup/sidekick/listAllRelateGroupId
- app/actionLibraryGroup/tabGroup
- app/actionLibraryGroup/trainingPartGroup
- app/actionLibraryGroup/userActionStatPage
- app/v2/actionLibraryGroup/page
- mobile/actionLibraryGroup/custom/trainingPartGroup
- mobile/actionLibraryGroup/trainingPartGroup

## actionLibraryTab
- app/actionLibraryTab/list
- app/v2/actionLibraryTab/group/list

## activity_badge_app_strategy
- app/activity_badge_app_strategy

## activityNew
- app/activityNew/detail
- app/activityNew/join
- app/activityNew/page
- app/activityNew/receiveAward
- app/activityNew/share
- app/activityNew/userRecordPage

## aiCourse
- app/aiCourse/buildDetail
- app/aiCourse/future/info
- app/aiCourse/hasChangeGoalOrCourse
- app/aiCourse/info
- app/aiCourse/info/preview
- app/aiCourse/saveFromDTO
- app/aiCourse/updateAiCourseActionSort

## aiCourseTrainingInfo
- mobile/aiCourseTrainingInfo/aiOutput
- mobile/aiCourseTrainingInfo/nutritionAdvice

## aiEntry
- app/aiEntry/getAiReply
- app/aiEntry/getHomeAdvice
- app/aiEntry/getRealtimeAdvice
- app/aiEntry/needAiAnalysis
- app/aiEntry/triggerRefresh

## aiGroupClassTrainingUserMethod
- app/aiGroupClassTrainingUserMethod/queryList
- app/aiGroupClassTrainingUserMethod/saveOrUpdate

## aiManualTrainingInfo
- mobile/aiManualTrainingInfo/addAiTrainingRecord
- mobile/aiManualTrainingInfo/getById
- mobile/aiManualTrainingInfo/update

## aiMessageOperationLog
- mobile/aiMessageOperationLog/list
- mobile/aiMessageOperationLog/save

## aiPlan
- mobile/aiPlan/detailk
- mobile/aiPlan/edit
- mobile/aiPlan/editDailyGoals
- mobile/aiPlan/goalBoard
- mobile/aiPlan/save

## aiPlanPreviewCourse
- app/aiPlanPreviewCourse/list

## aiTrainingGoal
- app/aiTrainingGoal/aiRecommendCoursesWeek
- app/aiTrainingGoal/detail
- app/aiTrainingGoal/edit
- app/aiTrainingGoal/editDayGoal
- app/aiTrainingGoal/editPreference
- app/aiTrainingGoal/preview

## appleMusic
- app/appleMusic/userAuthTokenSave
- app/appleMusic/userFlagCheck
- app/appleMusic/userScanStatusReach

## applePay
- app/applePay/v2/createOrder

## applicationVersion
- app/applicationVersion/lastVersion
- app/applicationVersion/lastVersion2
- app/applicationVersion/latest

## appServerInfo
- app/appServerInfo/list

## appUpdateLog
- app/appUpdateLog

## appUserConfig
- mobile/appUserConfig/info
- mobile/appUserConfig/save

## bikeAiCourseTrainingInfo
- mobile/bikeAiCourseTrainingInfo/aiOutput
- mobile/bikeAiCourseTrainingInfo/nutritionAdvice

## bikeCourseTrainingInfo
- mobile/bikeCourseTrainingInfo/aiOutput
- mobile/bikeCourseTrainingInfo/nutritionAdvice

## bikeFreeTrainingInfo
- mobile/bikeFreeTrainingInfo/aiOutput
- mobile/bikeFreeTrainingInfo/nutritionAdvice

## boatingSkiDataGraph
- app/boatingSkiDataGraph

## bodyFatMeasurement
- mobile/bodyFatMeasurement
- mobile/bodyFatMeasurement/dateType/latest
- mobile/bodyFatMeasurement/dateType/stat
- mobile/bodyFatMeasurement/dates
- mobile/bodyFatMeasurement/first
- mobile/bodyFatMeasurement/page
- mobile/bodyFatMeasurement/removeAllUnClaim
- mobile/bodyFatMeasurement/removeb
- mobile/bodyFatMeasurement/report
- mobile/bodyFatMeasurement/save
- mobile/bodyFatMeasurement/unClaimCount8
- mobile/bodyFatMeasurement/unClaimList
- mobile/bodyFatMeasurement/userTrainingStatus
- mobile/v3/bodyFatMeasurement/composition/statistics

## bodyFatScale
- mobile/bodyFatScale
- mobile/bodyFatScale/delete
- mobile/bodyFatScale/info
- mobile/bodyFatScale/save
- mobile/bodyFatScale/shortUserList
- mobile/bodyFatScale/transfer
- mobile/bodyFatScale/userInfo
- mobile/bodyFatScale/userList

## break_record_badge_app_strategy
- app/break_record_badge_app_strategy

## cardioImproveGoal
- app/cardioImproveGoal/ackNotifyPopup
- app/cardioImproveGoal/detail
- app/cardioImproveGoal/edit
- app/cardioImproveGoal/editDayGoals
- app/cardioImproveGoal/getUserPreference
- app/cardioImproveGoal/queryByDate

## chatAI
- mobile/chatAI/dailyKeyWordGen
- mobile/chatAI/foodRecordMsgRecords
- mobile/chatAI/genTrainingGoalDesc
- mobile/chatAI/getChatCounts
- mobile/chatAI/getConTextByScene
- mobile/chatAI/getFeedbackTypes
- mobile/chatAI/getTips{
- mobile/chatAI/manualTrainMsgRecords
- mobile/chatAI/message/feedbackl
- mobile/chatAI/openConText
- mobile/chatAI/saveFeedbackBehavior
- mobile/chatAI/send/stream/msg

## cmsPolicyAgreement
- app/cmsPolicyAgreement/agree
- app/cmsPolicyAgreement/popupCheck

## cmsPolicyDataInventory
- app/cmsPolicyDataInventory/reportDataCollectStatistics

## cmsUserScene
- app/cmsUserScene/agree
- app/cmsUserScene/fetchSettingList
- app/cmsUserScene/popupCheck

## cmsVersionNotice
- app/cmsVersionNotice/fetchVersionNoticeId

## coach
- app/coach/getAiCoachList

## common
- app/common/content/search/associations
- app/common/deviceErrorReport
- app/common/somatotype/configs

## commonConfig
- app/commonConfig/type
- app/commonConfig/type/20251120
- app/commonConfig/type/20260209
- app/commonConfig/typeZ

## commonStatusB
- app/commonStatusB

## componentHealth
- app/componentHealth/addComponentHealthLog
- app/componentHealth/closeTip
- app/componentHealth/confirmUserAlertFlag
- app/componentHealth/detail
- app/componentHealth/resetComponentHealth

## contentSinglePageConfig
- app/contentSinglePageConfig/detailByIndexCode

## course
- app/course/customizedInfo
- app/course/dayAdjustableList
- app/course/favoritesA
- app/course/getUserCourseStatPage
- app/course/newId
- app/course/saveCustomizea
- app/v2/course/changeActionPage
- app/v2/course/info
- app/v2/course/page
- app/v2/course/recommendCurrentWithGoal/list
- app/v2/course/recommendTabList

## courseBgColor
- app/courseBgColor/info

## coursecategory
- app/v2/coursecategory/group/list

## courseReservation
- app/courseReservation

## courseSnapshot
- app/courseSnapshot

## courseSportType
- app/courseSportType/listAll

## coursetraining
- app/coursetraining/needEvaluation
- app/coursetraining/save
- mobile/coursetraining/aiOutput
- mobile/coursetraining/nutritionAdvicec

## cttTrainingInfo
- app/cttTrainingInfo/save

## customTrainingTemplate
- app/customTrainingTemplate
- app/customTrainingTemplate/changeTrainingMethod
- app/customTrainingTemplate/generateAiCourse
- app/customTrainingTemplate/getActionLibraryListL
- app/customTrainingTemplate/getNextGroupParam
- app/customTrainingTemplate/getStatsData
- app/customTrainingTemplate/queryTrainingMethodDetail
- app/customTrainingTemplate/queryTrainingMethodList
- app/v2/customTrainingTemplate
- app/v2/customTrainingTemplate/copy
- app/v2/customTrainingTemplate/getUserTemplateStatPage
- app/v2/customTrainingTemplate/shareEvent
- app/v3/customTrainingTemplate/detailByCode
- app/v3/customTrainingTemplate/mergeListE
- app/v3/customTrainingTemplate/pinTop
- app/v4/customTrainingTemplate/appPage

## dataMigrationAgreement
- app/dataMigrationAgreement/contract
- app/dataMigrationAgreement/getContractStatus

## deepResearch
- mobile/deepResearch/aiVersion
- mobile/deepResearch/deleteSession
- mobile/deepResearch/queryHistoryMessage
- mobile/deepResearch/querySessionPage
- mobile/deepResearch/terminated

## deviceMatch
- app/deviceMatch/app/check

## dio
- mobile/dio/apple_music_mock_dao

## discovery
- app/discovery/exposure
- app/discovery/index
- app/discovery/list

## domain
- mobile/domain/device_type/device_type_display_cache_store
- mobile/domain/device_type/device_type_display_catalog
- mobile/domain/device_type/device_type_display_catalog_service
- mobile/domain/device_type/device_type_display_providers
- mobile/domain/device_type/device_type_display_repository
- mobile/domain/device_type/device_type_display_resolver
- mobile/domain/device_type/device_type_display_session
- mobile/domain/device_type/speediance_device_type
- mobile/domain/rope_position/rope_position_tree_sanitizer
- mobile/domain/target/ai_plan_api_gateway
- mobile/domain/target/ai_plan_observability
- mobile/domain/target/ai_target_diagnostic_log
- mobile/domain/target/network_ai_plan_api_data_source
- mobile/domain/target/user_goal_type_gate
- mobile/domain/target/user_goal_type_invalidation

## dtcInfo
- app/dtcInfo/queryDtcEnableSiteGrayUrlTypeList4
- app/dtcInfo/queryUserPointInfo

## environment
- app/environment/verifyCode

## eventReport
- app/eventReport/reportable/events
- app/eventReport/saveBatch

## exchange
- app/exchange/buyDirectSkuJ
- app/exchange/wellnessPlusMemberCard

## exclusivePlan
- app/exclusivePlan
- app/exclusivePlan/allowTraining
- app/exclusivePlan/current
- app/exclusivePlan/customized
- app/exclusivePlan/customizedInfo
- app/exclusivePlan/favorites
- app/exclusivePlan/join
- app/exclusivePlan/quit
- app/exclusivePlan/schedule
- app/exclusivePlan/start
- app/exclusivePlan/stop
- app/exclusivePlan/unfinishedCourseReminder
- app/exclusivePlan/unfinishedCourseReminder/action
- app/exclusivePlan/userExclusivePlan
- app/exclusivePlan/week
- app/v2/exclusivePlan/page
- app/v2/exclusivePlan/recommendList
- app/v2/exclusivePlan/tagGroup/listD
- app/v2/exclusivePlan/userRecordPage
- app/v2/exclusivePlan/weekTrainingFrequency
- mobile/exclusivePlan/page

## exclusivePlanCategory
- app/v2/exclusivePlanCategory/categoryGroup/list

## exclusivePlanStat
- app/exclusivePlanStat/buried

## family
- app/family

## fatLossDailyTask
- app/fatLossDailyTask/changeMainTasks
- app/fatLossDailyTask/changeSubTasks
- app/fatLossDailyTask/completeSubTasks
- app/fatLossDailyTask/unCompleteSubTasks

## fatLossGoal
- app/fatLossGoal/basicConfig
- app/fatLossGoal/confirmAlgorithmUpgrade
- app/fatLossGoal/dailyGoals
- app/fatLossGoal/detail
- app/fatLossGoal/trainingPlanW

## fatLossGoali
- app/fatLossGoali

## file
- mobile/file/presignedUpload
- mobile/file/sts
- mobile/file/sts/log

## foodEnergy
- mobile/foodEnergy/getFoodAndEnergy

## freetraining
- app/freetraining/save

## FromWatch
- mobile/FromWatch

## fromWave
- mobile/fromWave

## googlePay
- app/googlePay/checkUserSubscription
- app/googlePay/v2/createOrder

## growth
- app/growth/accountDetail

## heartDeviceMsg
- app/heartDeviceMsg/saveSegment

## homePageInfo
- app/homePageInfo/aiGoalBoard
- app/homePageInfo/boardInfo
- app/homePageInfo/cardioImproveGoalBoard
- app/homePageInfo/clearRealtimeAdvice
- app/homePageInfo/fatLossBoard
- app/homePageInfo/muscleBuildingBoard
- app/homePageInfo/recommendCourseModel
- app/homePageInfo/topState
- mobile/homePageInfo
- mobile/homePageInfo/superCardListT
- mobile/homePageInfo/topIndicatorVal

## i18nTranslate
- app/i18nTranslate/lastUpdateInfo

## in_progress_badge_app_strategy
- app/in_progress_badge_app_strategy

## indexBanner
- app/indexBanner/event
- app/indexBanner/info
- app/indexBanner/readStatus

## issueFeedback
- app/issueFeedback/submit3

## language
- app/language/openList

## login
- app/login/logout
- app/login/phoneo
- app/login/verifyEmail
- app/v2/login/byCode
- app/v2/login/byPass
- app/v2/login/bySns
- app/v2/login/byWechat2
- app/v2/login/register
- app/v2/login/resetPass
- app/v2/login/verifyIdentity

## main
- mobile/main

## manualTraining
- mobile/manualTraining/saveQ

## matDict
- app/matDict/getByDictType

## matLight
- app/matLight/list

## matUserConfig
- app/matUserConfig/get
- app/matUserConfig/update

## matUserMachine
- app/matUserMachine/allMachine
- app/matUserMachine/fetchBluetoothDeviceTypes
- app/matUserMachine/fetchBluetoothDevicesById
- app/matUserMachine/hasBindMachine
- app/matUserMachine/machineAccessories
- app/matUserMachine/rename
- app/matUserMachine/updateSnCode
- mobile/matUserMachine/checkBindStatus
- mobile/matUserMachine/delete
- mobile/matUserMachine/page
- mobile/matUserMachine/save

## medal
- app/medal/page
- app/v2/medal/activityCalendar
- app/v2/medal/activityMonth
- app/v2/medal/activityMonthDetail
- app/v2/medal/historyPage
- app/v2/medal/honorStage
- app/v2/medal/list
- app/v2/medal/trainingGroup

## medalGroup
- app/medalGroup/page

## member
- app/member/checkUserHasAuthRes
- app/member/getMemberAndFirstDiscount
- app/member/getShowDialogInfo
- app/member/getV2

## memberActivity
- app/memberActivity/getUserCurrentActivity

## memberBizTrial
- app/memberBizTrial/getRemainingDaysOfTrial

## memberCard
- app/memberCard/closePopUp
- app/memberCard/popUpI

## memberFamilyMember
- app/memberFamilyMember/activateFamilyMember
- app/memberFamilyMember/invitePopUp

## membershipPackage
- app/v3/membershipPackage/getBestDiscount
- app/v4/membershipPackage/detail
- app/v4/membershipPackage/getBestDiscount

## muscleBuildingGoal
- app/muscleBuildingGoal/capacityStat
- app/muscleBuildingGoal/config
- app/muscleBuildingGoal/editGoalsByDays
- app/muscleBuildingGoal/queryFatFreeMassIndexPage
- app/muscleBuildingGoal/queryMyGoal
- app/muscleBuildingGoal/share
- app/muscleBuildingGoal/update
- app/muscleBuildingGoal/updateMessageState
- app/muscleBuildingGoal/weeklyGoal
- app/muscleBuildingGoal/weeklyMilestone

## muscleLoad
- mobile/muscleLoad
- mobile/muscleLoad/detail

## myDay
- app/myDay/todoInfo
- mobile/myDay/v3/historyInfo

## nanoFreeTraining
- mobile/nanoFreeTraining/detail
- mobile/nanoFreeTraining/listRepBySetIndex

## nanoHyroxTraining
- mobile/nanoHyroxTraining/detail

## nfc
- mobile/nfc/login

## nfcx
- mobile/nfcx

## notification_on_kill
- mobile/notification_on_kill

## offlineEquipment
- app/offlineEquipment/listEnabled

## planTrainingInfo
- app/planTrainingInfo/save
- mobile/planTrainingInfo/aiOutput
- mobile/planTrainingInfo/nutritionAdvice

## poster
- app/poster

## questionnaire
- app/questionnaire

## quitTrainingReasonK
- app/quitTrainingReasonK

## reCommendCourse
- app/reCommendCourse/queryCourseByTypeAndDate

## redeemCenter
- app/redeemCenter/list
- app/v2/redeemCenter/list2
- app/v2/redeemCenter/redeem
- app/v2/redeemCenter/updateRedeem

## refer
- app/refer/detail
- app/refer/index
- app/refer/listConfigs
- app/refer/paymentDetail
- app/refer/rewardOrderPage
- app/refer/updatePayment

## register
- app/register/email/activation
- app/register/email2

## report
- app/report/index
- app/report/userTrainingData
- app/report/userTrainingStat
- app/report/weekly
- app/v2/report/resourceDataStat
- app/v3/report/getCoachShareImg
- mobile/v2/report/userTrainingDataRecord
- mobile/v2/report/userTrainingRecord
- mobile/v2/report/userTrainingStat

## router
- mobile/router/app_routes
- mobile/router/route_extra_registry
- mobile/router/routes/ai_coach_routes
- mobile/router/routes/all_in_one_routes
- mobile/router/routes/body_scale_routes
- mobile/router/routes/discovery_routes
- mobile/router/routes/female_health_routes
- mobile/router/routes/gm_lite_routes
- mobile/router/routes/gm_lite_routes_args
- mobile/router/routes/home_routers
- mobile/router/routes/home_routers_args
- mobile/router/routes/login_routes
- mobile/router/routes/login_routes_args
- mobile/router/routes/offline_training_routes
- mobile/router/routes/offline_training_routes_args
- mobile/router/routes/share_v2_routes
- mobile/router/routes/sidekick_routes
- mobile/router/routes/strap_routes
- mobile/router/routes/target_manage_routes
- mobile/router/routes/target_manage_routes_args
- mobile/router/routes/train_result_routes
- mobile/router/routes/train_result_routes_args
- mobile/router/routes/wellness_routes
- mobile/router/routes/wellness_routes_args
- mobile/router/routes/workouts_routes
- mobile/router/routes/workouts_routes_args
- mobile/router/workout_detail_navigation_session

## searchTerm
- app/searchTerm/enterDetail
- app/searchTerm/save

## setting
- app/setting/msg
- app/setting/privacyAgreement

## shareEvent
- app/shareEvent

## siriDietRecord
- mobile/siriDietRecord

## social_shareO
- mobile/social_shareO

## speedianceWarranty
- app/speedianceWarranty/extendedWarrantyActive
- app/speedianceWarranty/info

## sport_mileage_badge_app_strategy
- app/sport_mileage_badge_app_strategy

## sportTarget
- app/sportTarget/list

## sportTypeRecord
- mobile/sportTypeRecord/getTopList

## startSportTraining
- mobile/startSportTraining/listCalculating
- mobile/startSportTraining/saveSegment
- mobile/startSportTraining/v2/save
- mobile/startSportTraining/v2/updateMetrics
- mobile/startSportTraining/v2/updateTrainingStatus

## state
- mobile/state/global_data_logic
- mobile/state/locale_model
- mobile/state/platform_provider
- mobile/state/profile_change_notifier
- mobile/state/theme_config
- mobile/state/theme_model
- mobile/state/user_model

## strengthAssessmentAppointment
- app/strengthAssessmentAppointment/cancel
- app/strengthAssessmentAppointment/save

## strengthAssessmentReport
- app/strengthAssessmentReport/delete
- app/strengthAssessmentReport/detail
- app/strengthAssessmentReport/getPart
- app/strengthAssessmentReport/page
- app/strengthAssessmentReport/query1rmList

## strengthScore
- app/strengthScore/summary

## subscriber
- app/subscriber

## subscription
- app/subscription/extendWristbandMemberSubscription

## summarytraininginfo
- app/summarytraininginfo/trainingGrowth
- app/summarytraininginfo/trainingMedalHighlightPopupCheck

## superCardVersionRecord
- app/superCardVersionRecord/remove

## templateReservation
- app/templateReservation

## testPowerConfig
- app/testPowerConfig/testPartConfig

## toWave
- mobile/toWave

## trackLog
- app/trackLog/pageEvent
- app/trackLog/sportMode
- app/trackLog/training

## trainingCalendar
- app/v4/trainingCalendar/changeAICourse
- app/v5/trainingCalendar/dayNew
- app/v5/trainingCalendar/monthNewJ
- app/v6/trainingCalendar/planCalendar
- app/v6/trainingCalendar/planCalendarDay
- mobile/trainingCalendar/strength/listDateRange
- mobile/trainingCalendar/strength/staticByDate
- mobile/trainingCalendar/strength/summaryInfo

## trainingCommon
- mobile/trainingCommon/healthReport/info
- mobile/trainingCommon/info
- mobile/trainingCommon/updateSportCode

## trainingInfo
- app/trainingInfo/aiCourseTrainingInfo
- app/trainingInfo/aiCourseTrainingInfoDetail
- app/trainingInfo/courseTrainingInfo
- app/trainingInfo/courseTrainingInfoDetail
- app/trainingInfo/cttTrainingInfo
- app/trainingInfo/cttTrainingInfoDetail
- app/trainingInfo/freeTraining/P
- app/trainingInfo/freeTrainingDetail
- app/trainingInfo/getFreeTrainingId
- app/trainingInfo/planTrainingInfo
- app/trainingInfo/planTrainingInfoDetail
- app/trainingInfo/relationInfo
- app/trainingInfo/rpe

## trainingShare
- mobile/trainingShare/trainingRecord

## uopSurveyTrigger
- app/uopSurveyTrigger/recordClose
- app/uopSurveyTrigger/submitFeedback
- app/uopSurveyTrigger/trigger

## userActionLibraryGroupConfig
- app/userActionLibraryGroupConfig

## userActionLibraryWeight
- app/userActionLibraryWeight
- app/v2/userActionLibraryWeight

## userAddress
- app/userAddress/delete
- app/userAddress/getCountryAddress
- app/userAddress/getDefaultM
- app/userAddress/saveAndUpdate

## userBody
- app/userBody
- app/userBody/current
- app/userBody/firstTime
- app/userBody/page
- app/userBody/stat
- app/userBody/target
- app/userBody/weightGroupByDate/list

## userDataStat
- app/userDataStat/bikeRiding
- app/userDataStat/bikeRidingStatByDateType
- app/userDataStat/bikeRidingStatDetail
- app/userDataStat/boatingSki
- app/userDataStat/boatingSkiStatByDateType
- app/userDataStat/boatingSkiStatDetail
- app/userDataStat/calorieStatByDateType
- app/userDataStat/calorieStatDetail
- app/userDataStat/calorieV
- app/userDataStat/capacity
- app/userDataStat/capacityStatByDateType
- app/userDataStat/capacityStatDetail
- app/userDataStat/capacityStatDetailByDateRange
- app/userDataStat/courseStatByDateType
- app/userDataStat/courseStatDayPage3
- app/userDataStat/courseStatDetail
- app/userDataStat/courseStatIndex
- app/userDataStat/energy
- app/userDataStat/energyStatByDateType
- app/userDataStat/energyStatDetail
- app/userDataStat/heartRateStatByDateType
- app/userDataStat/heartRateStatIndex
- app/userDataStat/mileage
- app/userDataStat/mileageStatByDateType
- app/userDataStat/mileageStatDetailb
- app/userDataStat/strengthTraining
- app/userDataStat/trainingPartFatigueInfo
- app/userDataStat/trainingTime
- app/userDataStat/trainingTimeStatByDateType
- app/userDataStat/trainingTimeStatDetail
- mobile/userDataStat/heartRateStatDetail
- mobile/userDataStat/lastSeven/stat

## userDevice
- app/userDevice/info
- app/userDevice/typeDisplay

## userDietRecord
- app/userDietRecord/delete
- app/userDietRecord/list
- app/userDietRecord/saveForTypical
- app/userDietRecord/update
- app/userDietRecord/v2/save

## userExerciseHabit
- app/userExerciseHabit/getUserExerciseHabit
- app/userExerciseHabit/save

## userHealth
- mobile/userHealth
- mobile/userHealth/abnormal/count
- mobile/userHealth/abnormal/list
- mobile/userHealth/abnormal/save
- mobile/userHealth/addSleep
- mobile/userHealth/appIndex/healthData
- mobile/userHealth/baseline/latestRollingValue
- mobile/userHealth/bodyAge/detail
- mobile/userHealth/calendar/scores
- mobile/userHealth/compensationDataTime
- mobile/userHealth/compensationDataTime/save
- mobile/userHealth/dataSource/list
- mobile/userHealth/dataSource/sort
- mobile/userHealth/exposeRecord/batchIncrExposeCount
- mobile/userHealth/getUserHealthGirthIndicator
- mobile/userHealth/lastAddUserHealthDataTime2
- mobile/userHealth/mockReport/hasRealRecoveryData
- mobile/userHealth/mockReport/hasRealSleepData
- mobile/userHealth/mockReport/recoveryData
- mobile/userHealth/mockReport/sleepData
- mobile/userHealth/monitor/detail
- mobile/userHealth/monitor/index
- mobile/userHealth/newIndex/healthData
- mobile/userHealth/newIndex/healthDataIndicators
- mobile/userHealth/newIndex/healthScore
- mobile/userHealth/nutrition/dietReclistByDate
- mobile/userHealth/nutrition/getDietRecordAppleOtherList
- mobile/userHealth/nutrition/getDietRecordList
- mobile/userHealth/nutrition/getNearestDietRecordDate
- mobile/userHealth/nutrition/scoreDetail
- mobile/userHealth/physicalCondition/detailByDate
- mobile/userHealth/physicalCondition/listDailyDateRange
- mobile/userHealth/prs/save
- mobile/userHealth/recovery/detailByDate
- mobile/userHealth/sleep
- mobile/userHealth/sleep/rhythm
- mobile/userHealth/sleep/target/detail
- mobile/userHealth/sleep/target/save
- mobile/userHealth/sleepStandard
- mobile/userHealth/topIndicator/getByUserId
- mobile/userHealth/topIndicator/save
- mobile/userHealth/trainingLoad/dateRange
- mobile/userHealth/trainingLoadRecordList
- mobile/userHealth/widget/list

## userHealthDataReceive
- mobile/userHealthDataReceive/addUserHealthHistory
- mobile/userHealthDataReceive/batchSubmit
- mobile/userHealthDataReceive/finishStatusReceive
- mobile/userHealthDataReceive/latestReceiveTime8
- mobile/userHealthDataReceive/taskStatus
- mobile/userHealthDataReceive/uploadProgress

## userHealthReport
- mobile/userHealthReport/list
- mobile/userHealthReport/update

## userinfo
- app/userinfo
- app/userinfo/apple7
- app/userinfo/deauthorize
- app/userinfo/facebook
- app/userinfo/getStravaInfo
- app/userinfo/google
- app/userinfo/info
- app/userinfo/iosRegistrationId
- app/userinfo/save
- app/userinfo/scanO
- app/userinfo/setPwd
- app/userinfo/setting
- mobile/userinfo/changeEmail/confirm
- mobile/userinfo/changeEmail/sendCode
- mobile/userinfo/changeEmail/verifyPassword
- mobile/userinfo/completeAccount/confirm
- mobile/userinfo/completeAccount/confirmIdentity
- mobile/userinfo/completeAccount/sendCode

## userMeasurementData
- app/userMeasurementData/token

## userNotification
- app/v2/userNotification/event
- app/v2/userNotification/page
- app/v2/userNotification/status
- app/v2/userNotification/unreadCount

## userPic
- app/userPic/delete
- app/userPic/page
- app/userPic/save

## userPreference
- app/userPreference

## userRate
- mobile/userRate/detail
- mobile/userRate/update

## userSecurityAlert
- app/userSecurityAlert/status

## userStress
- mobile/userStress/dayCurve
- mobile/userStress/dayDuration
- mobile/userStress/history

## userTestPower
- app/userTestPower
- app/userTestPower/actionLibrary
- app/userTestPower/trainingPartListG
- app/v2/userTestPower
- app/v2/userTestPower/page
- app/v2/userTestPower/target

## userTrainingGoal
- app/userTrainingGoal/currentTodayGoal
- app/userTrainingGoal/page
- app/userTrainingGoal/pausePlan
- app/userTrainingGoal/quit
- app/userTrainingGoal/recoverPlanConfirm
- app/userTrainingGoal/save
- app/userTrainingGoal/stat
- app/userTrainingGoal/userGoalType
- app/v2/userTrainingGoal
- app/v2/userTrainingGoal/doBatchUpdateGoals
- app/v2/userTrainingGoal/recoverPlan

## verificationCode
- app/v2/verificationCode/send
- app/verificationCode/check
- app/verificationCode/send

## voiceFrameworkConfig
- app/voiceFrameworkConfig/default

## warningPopup
- app/warningPopup/errorCodeList

## watchMsg
- app/watchMsg/getHeartRateGraph
- app/watchMsg/getUserWatchOnline
- app/watchMsg/getUserWatchType

## weather
- app/weather/hourWeather

## wechat
- app/wechat/checkUserOrder
- app/wechat/v2/createAppPayTransaction

## widget
- mobile/widget

## wikiCategoryNew
- app/wikiCategoryNew/page

## wikiNew
- app/wikiNew
- app/wikiNew/page

## womenHealth
- app/womenHealth/landing/header
- mobile/womenHealth/landing/calendar
- mobile/womenHealth/landing/header
- mobile/womenHealth/onboarding
- mobile/womenHealth/periodRecords/markBleedingDay
- mobile/womenHealth/periodRecords/sync
- mobile/womenHealth/settings
- mobile/womenHealth/syncConfigTime
- mobile/womenHealth/wellnessCard
- mobile/womenHealth/wellnessCard/dismiss

## wristbandTraining
- mobile/wristbandTraining/confirm
- mobile/wristbandTraining/ignore
- mobile/wristbandTraining/markRead
- mobile/wristbandTraining/pendingList
- mobile/wristbandTraining/pendingSummary

## ws
- app/ws/watch/PAL
- app/ws/watch/WEBRTCMOBILE
- app/ws/watch/WEBRTCMOBILE/B
- app/ws/watch/WEBRTCMOBILE/E

