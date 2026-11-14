"""
数据分析 - 完整版，包含图表推荐
输出统计数据 + 文字分析结论 + 图表推荐
"""

import argparse
import json
import csv
from pathlib import Path
from typing import Any, Dict, List
from dataclasses import dataclass
import statistics


class ChartType:
    COLUMN = "column"
    BAR = "bar"
    PIE = "pie"
    HISTOGRAM = "histogram"
    BOX_PLOT = "box_plot"
    LINE = "line"


@dataclass
class ChartRecommendation:
    chart_type: str
    title: str
    data_source: str
    reason: str
    priority: int = 0


class ChartRecommender:
    """图表推荐器"""

    @staticmethod
    def recommend_for_categorical(field: str, categories: Dict, source: str) -> List[ChartRecommendation]:
        recommendations = []
        category_count = len(categories)

        if category_count <= 8:
            recommendations.append(ChartRecommendation(
                chart_type=ChartType.COLUMN,
                title=f"{field} 分布统计",
                data_source=f"tables/cat_{source}.csv",
                reason=f"分类数量适中（{category_count}个），柱状图清晰展示对比",
                priority=90
            ))

        if category_count > 8:
            recommendations.append(ChartRecommendation(
                chart_type=ChartType.BAR,
                title=f"{field} 分类统计",
                data_source=f"tables/cat_{source}.csv",
                reason=f"分类较多（{category_count}个），水平柱状图便于阅读",
                priority=85
            ))

        return recommendations

    @staticmethod
    def recommend_for_numeric(field: str, values: List[float], source: str) -> List[ChartRecommendation]:
        recommendations = []

        if len(values) < 2:
            return recommendations

        cv = statistics.stdev(values) / statistics.mean(values)

        if len(values) >= 20:
            recommendations.append(ChartRecommendation(
                chart_type=ChartType.HISTOGRAM,
                title=f"{field} 分布直方图",
                data_source=f"tables/stats_{source}.csv",
                reason=f"数据量充足（{len(values)}条），直方图展示分布特征",
                priority=95
            ))

        if cv > 0.3:
            recommendations.append(ChartRecommendation(
                chart_type=ChartType.BOX_PLOT,
                title=f"{field} 箱线图",
                data_source=f"tables/stats_{source}.csv",
                reason=f"数据离散度较高（CV={cv:.2f}），箱线图展示异常值",
                priority=75
            ))

        return recommendations


class Insight:
    """数据洞察生成器"""

    @staticmethod
    def describe_statistics(field: str, stats: Dict) -> str:
        return (
            f"{field}字段共{stats['count']}条记录，"
            f"平均值为{stats['mean']}，"
            f"中位数为{stats['median']}，"
            f"数值范围在{stats['min']}至{stats['max']}之间。"
        )

    @staticmethod
    def assess_distribution(values: List[float]) -> Dict:
        if len(values) < 2:
            return {"type": "insufficient_data"}

        mean_val = statistics.mean(values)
        stdev = statistics.stdev(values)
        cv = stdev / mean_val if mean_val != 0 else 0

        if cv < 0.1:
            variability = "低"
            stability = "数据分布相对均匀"
        elif cv < 0.3:
            variability = "中等"
            stability = "数据存在一定波动"
        else:
            variability = "高"
            stability = "数据波动较大，存在显著差异"

        median_val = statistics.median(values)
        if mean_val > median_val * 1.1:
            skew = "右偏"
        elif mean_val < median_val * 0.9:
            skew = "左偏"
        else:
            skew = "近似正态分布"

        return {
            "cv": round(cv, 3),
            "variability": variability,
            "stability": stability,
            "skew": skew
        }

    @staticmethod
    def detect_outliers(values: List[float]) -> List[float]:
        if len(values) < 4:
            return []

        sorted_vals = sorted(values)
        n = len(sorted_vals)
        q1 = sorted_vals[n // 4]
        q3 = sorted_vals[3 * n // 4]
        iqr = q3 - q1

        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr

        return [v for v in values if v < lower or v > upper]

    @staticmethod
    def describe_categories(field: str, cat_data: Dict) -> str:
        total = cat_data["total"]
        categories = cat_data["categories"]

        sorted_cats = sorted(categories.items(), key=lambda x: x[1], reverse=True)
        top_cat, top_count = sorted_cats[0]
        top_pct = top_count / total * 100
        diversity = len(categories)

        if diversity == 1:
            return f"{field}字段仅有1个类别：{top_cat}。"
        elif top_pct > 70:
            return f"{field}字段以{top_cat}为主，占比{top_pct:.1f}%，共{diversity}个类别。"
        else:
            return f"{field}字段分布较为分散，共{diversity}个类别，其中{top_cat}占比{top_pct:.1f}%。"

    @staticmethod
    def compare_to_threshold(field: str, stats: Dict, thresholds: Dict) -> List[str]:
        findings = []
        if field not in thresholds:
            return findings

        mean_val = stats["mean"]
        min_val = stats["min"]
        max_val = stats["max"]

        if "optimal_range" in thresholds[field]:
            low, high = thresholds[field]["optimal_range"]
            if mean_val < low:
                findings.append(f"{field}平均值({mean_val})低于适宜范围({low}-{high})")
            elif mean_val > high:
                findings.append(f"{field}平均值({mean_val})高于适宜范围({low}-{high})")
            else:
                findings.append(f"{field}平均值({mean_val})在适宜范围内({low}-{high})")

        if "critical_min" in thresholds[field] and min_val < thresholds[field]["critical_min"]:
            findings.append(f"注意：存在{field}低值({min_val})，低于临界值")

        if "critical_max" in thresholds[field] and max_val > thresholds[field]["critical_max"]:
            findings.append(f"注意：存在{field}高值({max_val})，超过临界值")

        return findings

    @staticmethod
    def generate_summary(field: str, stats: Dict, distribution: Dict, outliers: List, threshold_findings: List) -> str:
        parts = [Insight.describe_statistics(field, stats)]
        parts.append(f"数据{distribution['stability']}，{distribution['skew']}，变异程度为{distribution['variability']}。")

        if outliers:
            parts.append(f"检测到{len(outliers)}个异常值，建议进一步核实。")

        if threshold_findings:
            parts.extend(threshold_findings)

        return " ".join(parts)


class Analyzer:
    def __init__(self, mission_id: str, output_dir: str, numeric_fields: List[str] = None,
                 categorical_fields: Dict[str, str] = None, thresholds: Dict = None):
        self.mission_id = mission_id
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "tables").mkdir(exist_ok=True)

        self.numeric_fields = numeric_fields or []
        self.categorical_fields = categorical_fields or {}
        self.thresholds = thresholds or {}

        self.chart_recommender = ChartRecommender()
        self.data_characteristics = []

    def analyze(self, data_sources: Dict[str, str]) -> Dict:
        results = {
            "metadata": {"mission_id": self.mission_id, "version": "4.1-stdlib"},
            "sections": {},
            "charts": {}
        }

        if self.numeric_fields:
            results["sections"]["statistics"] = self._stat_analysis(data_sources)
        if self.categorical_fields:
            results["sections"]["categories"] = self._cat_analysis(data_sources)

        results["charts"] = self._generate_chart_recommendations()
        self._export(results)
        return results

    def _load_csv(self, path: str) -> List[Dict]:
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            return list(reader)

    def _stat_analysis(self, sources: Dict) -> Dict:
        results = {}
        for name, path in sources.items():
            try:
                data = self._load_csv(path)

                stats = {}
                for field in self.numeric_fields:
                    values = [float(row[field]) for row in data if row.get(field)]

                    if values:
                        field_stats = {
                            "count": len(values),
                            "mean": round(statistics.mean(values), 2),
                            "median": round(statistics.median(values), 2),
                            "min": round(min(values), 2),
                            "max": round(max(values), 2),
                            "stdev": round(statistics.stdev(values), 2) if len(values) > 1 else 0
                        }

                        distribution = Insight.assess_distribution(values)
                        outliers = Insight.detect_outliers(values)
                        threshold_findings = Insight.compare_to_threshold(field, field_stats, self.thresholds)
                        summary = Insight.generate_summary(field, field_stats, distribution, outliers, threshold_findings)

                        # 收集数据特征用于图表推荐
                        self.data_characteristics.append({
                            "type": "numeric",
                            "field": field,
                            "source": name,
                            "values": values
                        })

                        stats[field] = {
                            **field_stats,
                            "distribution": distribution,
                            "outliers_count": len(outliers),
                            "outliers": outliers[:5],
                            "threshold_findings": threshold_findings,
                            "summary": summary
                        }

                results[name] = stats
                self._export_stats_table(name, stats)

            except Exception as e:
                results[name] = {"error": str(e)}

        return results

    def _cat_analysis(self, sources: Dict) -> Dict:
        results = {}

        for name, path in sources.items():
            try:
                data = self._load_csv(path)
                field = self.categorical_fields.get(name)

                if not field:
                    continue

                categories = {}
                for row in data:
                    val = str(row.get(field, "未知"))
                    categories[val] = categories.get(val, 0) + 1

                total = sum(categories.values())

                description = Insight.describe_categories(field, {
                    "categories": categories,
                    "total": total
                })

                # 收集数据特征用于图表推荐
                self.data_characteristics.append({
                    "type": "categorical",
                    "field": field,
                    "source": name,
                    "categories": categories
                })

                results[name] = {
                    "field": field,
                    "categories": categories,
                    "total": total,
                    "unique_count": len(categories),
                    "description": description
                }

                self._export_cat_table(name, field, categories)

            except Exception as e:
                results[name] = {"error": str(e)}

        return results

    def _generate_chart_recommendations(self) -> Dict:
        recommendations = {}

        for char in self.data_characteristics:
            if char["type"] == "numeric":
                recs = self.chart_recommender.recommend_for_numeric(
                    char["field"], char["values"], char["source"]
                )
            elif char["type"] == "categorical":
                recs = self.chart_recommender.recommend_for_categorical(
                    char["field"], char["categories"], char["source"]
                )

            if recs:
                key = f"{char['source']}_{char['field']}"
                recommendations[key] = [
                    {
                        "chart_type": r.chart_type,
                        "title": r.title,
                        "data_source": r.data_source,
                        "reason": r.reason,
                        "priority": r.priority
                    }
                    for r in recs
                ]

        return recommendations

    def _export_stats_table(self, name: str, stats: Dict):
        with open(self.output_dir / "tables" / f"stats_{name}.csv", "w", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["字段", "数量", "均值", "中位数", "最小值", "最大值", "标准差"])
            for field, v in stats.items():
                writer.writerow([field, v["count"], v["mean"], v["median"], v["min"], v["max"], v["stdev"]])

    def _export_cat_table(self, name: str, field: str, cats: Dict):
        with open(self.output_dir / "tables" / f"cat_{name}.csv", "w", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([field, "数量", "占比"])
            total = sum(cats.values())
            for k, v in sorted(cats.items(), key=lambda x: x[1], reverse=True):
                writer.writerow([k, v, f"{v/total*100:.1f}%"])

    def _export(self, results: Dict):
        with open(self.output_dir / "report_summary.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        conclusions = self._extract_conclusions(results)
        with open(self.output_dir / "conclusions.json", "w", encoding="utf-8") as f:
            json.dump(conclusions, f, ensure_ascii=False, indent=2)

        charts = results.get("charts", {})
        if charts:
            with open(self.output_dir / "chart_recommendations.json", "w", encoding="utf-8") as f:
                json.dump(charts, f, ensure_ascii=False, indent=2)

        print(f"✓ 结果已保存到: {self.output_dir}")
        print(f"  - report_summary.json")
        print(f"  - conclusions.json")
        if charts:
            print(f"  - chart_recommendations.json")

    def _extract_conclusions(self, results: Dict) -> Dict:
        conclusions = {
            "title": f"{results['metadata']['mission_id']} 数据分析结论",
            "sections": {}
        }

        if "statistics" in results.get("sections", {}):
            stat_conclusions = []
            for source, fields in results["sections"]["statistics"].items():
                for field, data in fields.items():
                    if "summary" in data:
                        stat_conclusions.append({
                            "field": field,
                            "source": source,
                            "text": data["summary"]
                        })
            conclusions["sections"]["statistics"] = stat_conclusions

        if "categories" in results.get("sections", {}):
            cat_conclusions = []
            for source, data in results["sections"]["categories"].items():
                if "description" in data:
                    cat_conclusions.append({
                        "source": source,
                        "text": data["description"]
                    })
            conclusions["sections"]["categories"] = cat_conclusions

        return conclusions


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="数据分析工具（纯 Python 内置库）")
    parser.add_argument("--mission-id", required=True, help="任务标识符")
    parser.add_argument("--output-dir", default="./output", help="输出目录")
    parser.add_argument("--data-sources", required=True, help="数据源 JSON: {\"name\": \"path.csv\"}")
    parser.add_argument("--numeric-fields", help="数值字段列表，逗号分隔: field1,field2")
    parser.add_argument("--categorical-fields", help="分类字段 JSON: {\"source\": \"field\"}")
    parser.add_argument("--thresholds", help="阈值配置 JSON（可选）")

    args = parser.parse_args()

    sources = json.loads(args.data_sources)
    numeric_fields = args.numeric_fields.split(",") if args.numeric_fields else []
    categorical_fields = json.loads(args.categorical_fields) if args.categorical_fields else {}
    thresholds = json.loads(args.thresholds) if args.thresholds else {}

    analyzer = Analyzer(args.mission_id, args.output_dir, numeric_fields, categorical_fields, thresholds)
    analyzer.analyze(sources)
