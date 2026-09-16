-- wf#4841 full SQL
-- engineer: gcl
-- db_name: hly_accesscard
-- status: workflow_finish
-- finish_time: 2026-09-16 17:19:19.219924
--
-- 业务方实测 wf#4841 实际包含 8 条 SQL:
--   [0] CREATE TABLE vehicle_risk_hit
--   [1] CREATE TABLE vehicle_risk_hit_detail
--   [2] CREATE TABLE risk_rule_set
--   [3] CREATE TABLE risk_rule_operation_log
--   [4] ALTER TABLE accesscard_licensefront_info ADD owner_name ...  ← gh-ost 实际处理 (statement_index=0)
--   [5] ALTER TABLE vehicle_info_verify ADD data_source ...
--   [6] ALTER TABLE accesscard_vehicle_review ADD risk_level ...
--   [7] ALTER TABLE accesscard_opendcardapply ADD 3 columns ...
--
-- gh-ost 只处理 statement_index=0 那一条 (切流 481463/481463 行成功)
-- 其余 7 条 (4 CREATE + 3 ALTER) 没执行, 工单状态显示 '已正常结束'
-- 业务方需要 review 下面 8 条 SQL, 自己决定哪些要补建/补执行
---

-- #23807【ETC】业务风险管理上线
-- 增加业务风险校验（分为高、中、低三类风险），针对不同风险触发不同策略（缴纳风险首充款等）
CREATE TABLE `vehicle_risk_hit` (
  `id` bigint NOT NULL COMMENT '主键id',
  `user_id` bigint DEFAULT NULL COMMENT '用户id',
  `mobile_tel` varchar(20)   DEFAULT NULL COMMENT '移动电话',
  `vehicle_plate` varchar(20) DEFAULT NULL COMMENT '车牌号码',
  `vehicle_color` varchar(10) DEFAULT NULL COMMENT '车牌颜色（数据字典：车牌颜色 vehicle_color）',
  `rule_set_code` varchar(50) DEFAULT NULL COMMENT '规则集编号（如：R01）',
  `latest_detail_id` bigint DEFAULT NULL COMMENT '最新的明细id=vehicle_risk_hit_detail.id',
  `max_risk_level` tinyint DEFAULT NULL COMMENT '已触发的最高风险等级（0-无风险；1-命中, 2-低风险, 3-中风险, 4-高风险）',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `open_card_apply_id` bigint DEFAULT NULL COMMENT '开卡申请Id',
  `vehicle_id` bigint DEFAULT NULL COMMENT '车辆Id',
  `apply_case` tinyint DEFAULT '1' COMMENT '触发场景：1-ETC办理, 2-ETC使用',
  `card_type` varchar(50) DEFAULT NULL COMMENT '卡类型',
  `vehicle_status` tinyint DEFAULT NULL COMMENT '车辆状态（1未提单，2已提单，3审核成功，4审核失败，5发行成功）',
  `apply_channel` varchar(50)   DEFAULT NULL COMMENT '办理渠道，数据字典：etc_apply_channel',
  PRIMARY KEY (`id`)
)  COMMENT='车辆业务风险命中记录（主表）';

-- 新增表 hly_accesscard.vehicle_risk_hit_detail 车辆业务风险命中记录明细（明细表）
CREATE TABLE `vehicle_risk_hit_detail` (
  `id` bigint NOT NULL COMMENT '主键id',
  `hit_id` bigint DEFAULT NULL COMMENT '关联的主表id=vehicle_risk_hit.id',
  `user_id` bigint DEFAULT NULL COMMENT '用户id',
  `mobile_tel` varchar(20)  DEFAULT NULL COMMENT '移动电话',
  `vehicle_plate` varchar(20) DEFAULT NULL COMMENT '车牌号码',
  `vehicle_color` varchar(10) DEFAULT NULL COMMENT '车牌颜色（数据字典：车牌颜色 vehicle_color）',
  `card_type` varchar(50) DEFAULT NULL COMMENT '卡类型:1:徽通卡 ,2:苏通卡95折 ,3:苏通卡85折 ,4:八桂行卡 ,5:浙通卡 ,6:通渝卡 ,7:赣通卡 ,8:招商畅行卡；字典:open_card_type',
  `risk_level` tinyint DEFAULT NULL COMMENT '命中的业务风险等级（0-无风险；1-命中, 2-低风险, 3-中风险, 4-高风险），数据字典：业务风险等级,risk_level',
  `apply_case` tinyint DEFAULT NULL COMMENT '触发场景：1-ETC办理, 2-ETC使用',
  `apply_channel` varchar(50) DEFAULT NULL COMMENT '办理渠道，数据字典：etc_apply_channel',
  `apply_page` varchar(50) DEFAULT NULL COMMENT '应用页面（如：车辆图片上传页）',
  `rule_set_code` varchar(50) DEFAULT NULL COMMENT '风险规则集编号（如：R01）',
  `rule_code` varchar(50)  DEFAULT NULL COMMENT '风险规则编号，如：R04-1, R04-8-01',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `remind_flag` tinyint DEFAULT '0' COMMENT '是否提醒过：0未提醒（默认）；1已提醒',
  `remark` varchar(100) DEFAULT NULL COMMENT '校验结果描述',
  PRIMARY KEY (`id`),
  KEY `idx_vehicle_risk_hit_detail_hit_id` (`hit_id`) USING BTREE
)   COMMENT='车辆业务风险命中记录明细（明细表）';

CREATE TABLE `risk_rule_set` (
  `id` bigint unsigned NOT NULL COMMENT '主键ID',
  `rule_set_name` varchar(100) DEFAULT NULL COMMENT '规则集名称',
  `node_level` tinyint NOT NULL COMMENT '节点层级：1-规则集(Level1), 2-规则组(Level2), 3-规则明细(Level3)',
  `rule_code` varchar(50) DEFAULT NULL COMMENT '规则编号，如 R01, R04-1, R04-8-01',
  `rule_set_code` varchar(50) DEFAULT NULL COMMENT '规则集编号（如：R01）',
  `rule_sub_code` varchar(50) DEFAULT NULL COMMENT '规则子集编号（如：- 或 R01-01）',
  `rule_name` varchar(255) DEFAULT NULL COMMENT '规则名称/内容描述',
  `trigger_condition` varchar(100) DEFAULT NULL COMMENT '触发条件',
  `core_function` varchar(255) DEFAULT NULL COMMENT '核心作用/逻辑描述',
  `vehicle_type` varchar(100) DEFAULT NULL COMMENT '适用车型',
  `status` tinyint NOT NULL DEFAULT '1' COMMENT '状态：1-开启, 0-关闭',
  `risk_level` tinyint DEFAULT NULL COMMENT '业务风险等级如：0无风险、1命中、2低风险、3中风险、4高风险',
  `apply_rule` varchar(50) DEFAULT NULL COMMENT '应用规则/处置策略',
  `risk_reminder` varchar(255) DEFAULT NULL COMMENT '风险提醒内容',
  `apply_page` varchar(50) DEFAULT NULL COMMENT '应用页面',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `apply_case` tinyint DEFAULT NULL COMMENT '应用场景：1-ETC办理, 2-ETC使用',
  `action` varchar(150) DEFAULT NULL COMMENT '动作',
  `is_risk_remind` tinyint DEFAULT NULL COMMENT '是否风险提醒1-是, 0-否',
  `action_reminder` varchar(255) DEFAULT NULL COMMENT '动作提示内容',
  PRIMARY KEY (`id`),
  KEY `idx_parent_id` (`rule_set_name`),
  KEY `idx_rule_code` (`rule_code`)
) COMMENT='风险规则集表';

CREATE TABLE `risk_rule_operation_log` (
  `id` bigint unsigned NOT NULL COMMENT '主键ID',
  `rule_id` bigint unsigned NOT NULL COMMENT '关联的风控规则ID (对应 risk_rule_set.id)',
  `operator` varchar(64) NOT NULL COMMENT '操作人/账号',
  `operation_type` tinyint NOT NULL COMMENT '操作类型 (1新增/2编辑)',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '操作时间',
  `description` varchar(255) DEFAULT NULL COMMENT '操作描述/变更详情',
  PRIMARY KEY (`id`),
  KEY `idx_rule_id` (`rule_id`)
) COMMENT='风控规则操作记录表';


-- 行驶证正面的ocr识别结果表，加字段，增加所有人信息
ALTER TABLE hly_accesscard.accesscard_licensefront_info ADD owner_name varchar(200) NULL COMMENT '所有人';

-- 车辆校验表，新增一个字段
ALTER TABLE hly_accesscard.vehicle_info_verify ADD data_source tinyint NULL COMMENT '数据来源：2开卡发行';
ALTER TABLE `accesscard_vehicle_review` ADD COLUMN `risk_level` TINYINT DEFAULT NULL COMMENT '业务风险等级（如：0无风险、1命中、2低风险、3中风险、4高风险） ';	

ALTER TABLE `accesscard_opendcardapply` 
ADD COLUMN `agency_spread_code` varchar(50) DEFAULT NULL COMMENT '（推荐码-代理）', 
ADD COLUMN `spread_user` varchar(50) DEFAULT NULL COMMENT '（推荐人）' , 
ADD COLUMN `risk_level` tinyint NULL COMMENT '业务风险等级（如：1命中、2高风险、3中风险、3低风险）',
ADD COLUMN `agency_spread_user` varchar(50) DEFAULT NULL COMMENT '（推荐人-代理）' ;